"""Refuse TipRay ciphertext and non-UTF-8 text in what Git records.

Usage:
  python scripts/check_plaintext.py --staged        # pre-commit hook: files staged for commit
  python scripts/check_plaintext.py --commit <rev>  # deploy script: every file in <rev>

Reads Git objects, not the working tree: TipRay may hand a process decrypted
bytes on disk while Git stores ciphertext.
"""
import subprocess
import sys

MAGIC = b"%TSD-Header-###%"
TEXT_SUFFIXES = (
    ".py", ".js", ".mjs", ".cjs", ".ts", ".vue", ".json", ".md", ".csv", ".html", ".css",
    ".txt", ".yml", ".yaml", ".toml", ".ps1", ".sh", ".cfg", ".ini", ".in", ".sql",
)


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def objects(argv):
    if argv == ["--staged"]:
        out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
        return [(":" + path, path) for path in out.decode("utf-8").split("\0") if path]
    if len(argv) == 2 and argv[0] == "--commit":
        found = []
        for record in git("ls-tree", "-r", "-z", argv[1]).decode("utf-8").split("\0"):
            if not record:
                continue
            meta, path = record.split("\t", 1)
            _mode, kind, sha = meta.split()
            if kind == "blob":
                found.append((sha, path))
        return found
    sys.exit(__doc__)


def main():
    items = objects(sys.argv[1:])
    batch = subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    encrypted, not_utf8 = [], []
    for obj, path in items:
        batch.stdin.write(obj.encode("utf-8") + b"\n")
        batch.stdin.flush()
        header = batch.stdout.readline().split()
        if header[-1] == b"missing":
            continue
        data = batch.stdout.read(int(header[2]))
        batch.stdout.read(1)
        if data.startswith(MAGIC):
            encrypted.append(path)
        elif path.lower().endswith(TEXT_SUFFIXES):
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                not_utf8.append(path)
    batch.stdin.close()
    batch.wait()

    for path in encrypted:
        print("TipRay ciphertext: " + path)
    for path in not_utf8:
        print("not UTF-8 text:    " + path)
    if encrypted or not_utf8:
        print("Refused. Rewrite these files with the plaintext-safe writer in CLAUDE.md / AGENTS.md, "
              "or restore unchanged ones with git checkout -- <path>.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
