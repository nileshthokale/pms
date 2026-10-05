"""Confirm the production database's logical content matches a recent copy."""

import os
import sqlite3
import sys
import tempfile

PRODUCTION = os.path.join("data", "pharmacy.db")
COPY = os.path.join(tempfile.gettempdir(), "pharmacy_realdata_print_copy.db")


def tables_and_counts(path):
    uri = "file:" + os.path.abspath(path).replace(os.sep, "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        names = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                for name in names}
    finally:
        conn.close()


def digest(path):
    uri = "file:" + os.path.abspath(path).replace(os.sep, "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        names = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        import hashlib
        digest = hashlib.sha256()
        for name in names:
            digest.update(name.encode())
            for row in conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid'):
                digest.update(repr(row).encode("utf-8", "replace"))
        return digest.hexdigest()
    finally:
        conn.close()


live = tables_and_counts(PRODUCTION)
copy = tables_and_counts(COPY)

print(f"production : {os.path.getsize(PRODUCTION)} bytes, {len(live)} tables")
print(f"copy       : {os.path.getsize(COPY)} bytes, {len(copy)} tables")

missing = sorted(set(live) - set(copy))
added = sorted(set(copy) - set(live))
diff = {t: (live[t], copy[t]) for t in live if t in copy and live[t] != copy[t]}
print(f"tables only in production : {missing or 'none'}")
print(f"tables only in copy       : {added or 'none'}")
print(f"row-count differences     : {diff or 'none'}")

live_digest = digest(PRODUCTION)
copy_digest = digest(COPY)
print()
print(f"production content digest: {live_digest}")
print(f"copy content digest      : {copy_digest}")
print("CONTENT IDENTICAL" if live_digest == copy_digest else "CONTENT DIFFERS")
sys.exit(0 if live_digest == copy_digest else 1)
