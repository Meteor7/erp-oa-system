"""Run explicitly in an isolated MariaDB/Frappe site, never a business site.

RAYHER_REVIEW_SITE=review.localhost env/bin/python -m pytest -q scripts/qa/test_transaction_locks.py
The site must have review_isolated=true and a review-* DB host. No public ports.
"""
import hashlib
import os
import select
import subprocess
import sys
import time

import frappe
import pymysql
import pytest

SITE = os.environ.get("RAYHER_REVIEW_SITE")
SITES = os.environ.get("RAYHER_REVIEW_SITES", "/sandbox/bench/sites")


def connect():
    if SITE != "review.localhost":
        raise RuntimeError("Requires the isolated review site")
    frappe.init(site=SITE, sites_path=SITES)
    if not frappe.conf.get("review_isolated") or frappe.conf.db_host != "rayher-review-db":
        raise RuntimeError("Refusing to run mutation tests on a non-review database")
    frappe.connect()


@pytest.fixture(autouse=True)
def isolated_site():
    connect()
    try:
        yield
    finally:
        frappe.db.rollback()
        frappe.destroy()


def contender(key, wait=0):
    connection = pymysql.connect(host="rayher-review-db", user="root", database="review_audit")
    with connection.cursor() as cursor:
        cursor.execute("SELECT GET_LOCK(%s, %s)", (hashlib.sha256(key.encode()).hexdigest(), wait))
        acquired = cursor.fetchone()[0]
    connection.close()
    return acquired


def test_reentrant_lock_is_held_through_commit():
    from rayher_hr_payroll.invoice_ocr.service import _transaction_lock, _lock_key
    key = _lock_key("request", "review-commit")
    with _transaction_lock("request", "review-commit"):
        with _transaction_lock("request", "review-commit"):
            assert contender(key) == 0
        assert contender(key) == 0
    assert contender(key) == 0
    frappe.db.commit()
    assert contender(key) == 1


def test_exception_does_not_release_before_rollback():
    from rayher_hr_payroll.invoice_ocr.service import _transaction_lock, _lock_key
    key = _lock_key("request", "review-rollback")
    with pytest.raises(ValueError):
        with _transaction_lock("request", "review-rollback"):
            raise ValueError("fault injection")
    assert contender(key) == 0
    frappe.db.rollback()
    assert contender(key) == 1


def test_live_transaction_cannot_outlive_its_lock():
    from rayher_hr_payroll.invoice_ocr.service import _transaction_lock, _lock_key
    key = _lock_key("record", "review-long")
    with _transaction_lock("record", "review-long", timeout=1):
        time.sleep(1.1)
        assert contender(key) == 0
    frappe.db.commit()
    assert contender(key) == 1


def test_killed_worker_releases_lock_and_rolls_back_database():
    from rayher_hr_payroll.invoice_ocr.service import _transaction_lock, _lock_key
    frappe.db.sql("CREATE TABLE IF NOT EXISTS review_lock_probe (id INT PRIMARY KEY, value INT) ENGINE=InnoDB")
    frappe.db.sql("REPLACE INTO review_lock_probe VALUES (1, 0)")
    frappe.db.commit()
    code = """import frappe,time,os
frappe.init(site='review.localhost',sites_path='/sandbox/bench/sites')
assert frappe.conf.review_isolated and frappe.conf.db_host == 'rayher-review-db'
frappe.connect()
from rayher_hr_payroll.invoice_ocr.service import _transaction_lock
with _transaction_lock('request','review-killed'):
 frappe.db.sql('UPDATE review_lock_probe SET value=99 WHERE id=1')
 print('acquired',flush=True)
 time.sleep(60)
"""
    worker = subprocess.Popen([sys.executable, "-u", "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready, _, _ = select.select([worker.stdout], [], [], 15)
        assert ready, "Worker did not acquire lock"
        assert worker.stdout.readline().strip() == "acquired"
        assert contender(_lock_key("request", "review-killed")) == 0
        start = time.monotonic()
        worker.kill()  # SIGKILL deliberately bypasses Python finally and DB callbacks.
        worker.wait(timeout=10)
        with _transaction_lock("request", "review-killed", blocking_timeout=5):
            assert frappe.db.sql("SELECT value FROM review_lock_probe WHERE id=1 FOR UPDATE")[0][0] == 0
        assert time.monotonic() - start < 5
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.communicate(timeout=10)


def test_connection_close_releases_without_transaction_callbacks():
    from rayher_hr_payroll.invoice_ocr.service import _transaction_lock, _lock_key
    key = _lock_key("request", "review-disconnected")
    with _transaction_lock("request", "review-disconnected"):
        assert contender(key) == 0
    frappe.db.close()
    assert contender(key) == 1
    # Late rollback callback must not unlock a different session or reconnect
    # just to release the previous session's mutex.
    frappe.db.after_rollback.run()


def test_parallel_transactions_preserve_all_updates():
    frappe.db.sql("CREATE TABLE IF NOT EXISTS review_lock_probe (id INT PRIMARY KEY, value INT) ENGINE=InnoDB")
    frappe.db.sql("REPLACE INTO review_lock_probe VALUES (2, 0)")
    frappe.db.commit()
    code = """import frappe,time
frappe.init(site='review.localhost',sites_path='/sandbox/bench/sites')
assert frappe.conf.review_isolated and frappe.conf.db_host == 'rayher-review-db'
frappe.connect()
from rayher_hr_payroll.invoice_ocr.service import _transaction_lock
try:
 for _ in range(5):
  with _transaction_lock('request','review-parallel'):
   value=frappe.db.sql('SELECT value FROM review_lock_probe WHERE id=2 FOR UPDATE')[0][0]
   time.sleep(0.01)
   frappe.db.sql('UPDATE review_lock_probe SET value=%s WHERE id=2',(value+1,))
  frappe.db.commit()
finally:
 frappe.db.rollback();frappe.destroy()
"""
    workers = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    try:
        for worker in workers:
            out, err = worker.communicate(timeout=30)
            assert worker.returncode == 0, err
        assert frappe.db.sql("SELECT value FROM review_lock_probe WHERE id=2 FOR UPDATE")[0][0] == 20
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=5)
