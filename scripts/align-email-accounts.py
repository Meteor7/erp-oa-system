"""Transactional ERP account alignment from a verified private company-email mapping.
Run from the bench directory through env/bin/python, providing JSON on stdin.
No source files are edited by this tool. Mutations require maintenance mode,
a fresh full database backup, and a matching preflight fingerprint.
"""
from __future__ import annotations
import collections
import gzip
import hashlib
import json
import pathlib
import re
import sys
import time
import pymysql

VOLATILE = {"tabSessions", "tabActivity Log", "tabAccess Log", "tabError Log",
            "tabScheduled Job Log", "tabRQ Job", "tabConsole Log", "__global_search"}

def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=True, sort_keys=True, default=str).encode()).hexdigest()

def quote(name):
    return "`" + name.replace("`", "``") + "`"

def replace(value, mapping):
    if isinstance(value, dict):
        return {mapping.get(k, k): replace(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [replace(v, mapping) for v in value]
    if not isinstance(value, str):
        return value
    if value in mapping:
        return mapping[value]
    if value[:1] in ("[", "{"):
        try:
            old = json.loads(value)
        except ValueError:
            return value
        new = replace(old, mapping)
        if new != old:
            return json.dumps(new, ensure_ascii=False, separators=(",", ":"))
    return value

def read_all(cursor, schema):
    result = {}
    for table in schema:
        cursor.execute("SELECT * FROM " + quote(table))
        result[table] = cursor.fetchall()
    return result

def fingerprints(data):
    return {table: {"count": len(rows), "digest": digest(sorted(digest(r) for r in rows))}
            for table, rows in data.items()}

def prepare(data, records):
    users = {r["name"]: r for r in data["tabUser"]}
    employees = {r["name"]: r for r in data["tabEmployee"]}
    mapping = {}
    retired = set()
    targets = set()
    for r in records:
        old, new = r["old_user"], r["target_user"]
        if new != r["company_email"].split("@")[0] + "@staff.example.invalid":
            raise ValueError("Target must use the company's exact email prefix")
        if new in targets:
            raise ValueError("Duplicate target: " + new)
        targets.add(new)
        if old not in users or employees[r["employee"]]["user_id"] != old or employees[r["employee"]]["employee_name"] != r["person"]:
            raise ValueError("Employee binding changed: " + old)
        if new in users and old != new:
            if r.get("retire_user") != new or users[new]["enabled"] or users[new]["full_name"] != r["person"] or any(e["user_id"] == new for e in employees.values()):
                raise ValueError("Target occupied by another account: " + new)
            target = r["retired_target"]
            if target in users:
                raise ValueError("Retired target occupied")
            mapping[new] = target
            retired.add(new)
        if old != new:
            mapping[old] = new
    for r in records:
        if any(u.get("username") == r["username"] and u["name"] != r["old_user"] for u in users.values()):
            raise ValueError("Username occupied: " + r["username"])
    usernames = {r["old_user"]: r["username"] for r in records}
    displays = {r["old_user"]: r for r in records if r.get("display_name")}
    employee_displays = {r["employee"]: r for r in records if r.get("display_name")}
    employee_emails = {r["employee"]: r["company_email"] for r in records if r.get("sync_company_email")}
    expected = {}; operations = []
    for table, rows in data.items():
        expected[table] = []
        for row in sorted(rows, key=lambda x: 0 if x.get("name") in retired else 1):
            new = {k: replace(v, mapping) if not (table == "__Auth" and k == "password") else v for k, v in row.items()}
            if table == "tabUser" and row["name"] in usernames:
                new["username"] = usernames[row["name"]]
            # Contact email changes require an explicit synchronization request.
            if table == "tabEmployee":
                new["company_email"] = employee_emails.get(row["name"], row.get("company_email"))
            if table == "tabUser" and row["name"] in displays:
                display = displays[row["name"]]["display_name"]
                new.update(first_name=display, middle_name=None, last_name=None, full_name=display)
            if table == "tabEmployee" and row["name"] in employee_displays:
                r = employee_displays[row["name"]]
                new.update(first_name=r["display_name"], employee_name=r["display_name"], company_email=r["company_email"])
                for field in ("middle_name", "last_name"):
                    if field in new:
                        new[field] = None
            expected[table].append(new)
            changed = {k: v for k, v in new.items() if row[k] != v}
            if changed:
                operations.append((table, row, changed))
    return mapping, expected, operations

def verify_backup(path, database):
    p = pathlib.Path(path)
    if not p.is_file() or not 0 <= time.time() - p.stat().st_mtime < 3600:
        raise ValueError("Fresh backup required")
    with gzip.open(p, "rb") as stream:
        header = stream.read(2048)
        match = re.search(rb"^-- Host:.*?Database:\s*(\S+)", header, re.MULTILINE)
        if not match or match.group(1).decode() != database:
            raise ValueError("Backup database does not match")
        while stream.read(1024 * 1024):
            pass
    return {"path": str(p), "bytes": p.stat().st_size}

def main():
    payload = json.load(sys.stdin)
    site = payload.get("site", "rayher.localhost")
    config = json.loads(pathlib.Path("sites", site, "site_config.json").read_text())
    common = json.loads(pathlib.Path("sites/common_site_config.json").read_text())
    db = pymysql.connect(host=config.get("db_host", common.get("db_host", "127.0.0.1")),
        port=int(config.get("db_port", common.get("db_port", 3306))),
        user=config.get("db_user", config["db_name"]), password=config["db_password"],
        database=config["db_name"], charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    cursor = db.cursor(); committed = False
    try:
        cursor.execute("SELECT GET_LOCK('company_email_account_alignment', 0) AS acquired")
        if cursor.fetchone()["acquired"] != 1:
            raise ValueError("Another account alignment is running")
        cursor.execute("SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", config["db_name"])
        engines = {r["TABLE_NAME"]: r["ENGINE"] for r in cursor.fetchall() if r["TABLE_NAME"] not in VOLATILE}
        cursor.execute("SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=%s AND CONSTRAINT_NAME='PRIMARY' ORDER BY TABLE_NAME,ORDINAL_POSITION", config["db_name"])
        primary = collections.defaultdict(list)
        for r in cursor.fetchall():
            primary[r["TABLE_NAME"]].append(r["COLUMN_NAME"])
        cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
        before = read_all(cursor, engines)
        mapping, expected, operations = prepare(before, payload["records"])
        fp = digest({"before": fingerprints(before), "records": payload["records"]})
        changed_tables = collections.Counter(t for t, _, _ in operations)
        for table in changed_tables:
            if engines[table] != "InnoDB" or not primary[table]:
                raise ValueError("Updated table is not transactional or has no primary key: " + table)
        result = {"state": "planned", "site": site, "fingerprint": fp, "accounts": len(payload["records"]),
                  "renames": len(mapping), "changed_rows": dict(changed_tables), "tables_checked": len(before)}
        mode = payload.get("mode", "plan")
        if mode == "plan":
            print(json.dumps(result, ensure_ascii=True)); return
        if not config.get("maintenance_mode", common.get("maintenance_mode")):
            raise ValueError("Maintenance mode is required")
        result["backup"] = verify_backup(payload["backup_path"], config["db_name"])
        if payload.get("expected_fingerprint") != fp:
            raise ValueError("Preflight fingerprint changed; rerun plan")
        for table, row, changed in operations:
            keys = primary[table]
            sql = "UPDATE " + quote(table) + " SET " + ",".join(quote(k) + "=%s" for k in changed)
            sql += " WHERE " + " AND ".join(quote(k) + " <=> %s" for k in keys)
            cursor.execute(sql, [*changed.values(), *(row[k] for k in keys)])
            if cursor.rowcount != 1:
                raise ValueError("Updated row count mismatch: " + table)
        after = read_all(cursor, engines)
        if fingerprints(after) != fingerprints(expected):
            raise ValueError("Database preservation check failed")
        # Verify all passwords, permissions and historical rows as part of the
        # full database comparison before allowing a single commit.
        if mode == "rehearse":
            db.rollback(); result["state"] = "rehearsed-and-rolled-back"
        elif mode == "apply":
            db.commit(); committed = True; result["state"] = "committed"
        else:
            raise ValueError("Unknown mode")
        result["database_preserved"] = True
        print(json.dumps(result, ensure_ascii=True))
    finally:
        if not committed:
            db.rollback()
        cursor.execute("SELECT RELEASE_LOCK('company_email_account_alignment')")
        db.close()

if __name__ == "__main__":
    main()
