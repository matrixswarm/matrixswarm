"""Memory SQLite catalogue and separate authenticated encrypted objects.

The existing EncryptedStateMixin owns key derivation and atomic encrypted-file
writes. No plaintext SQLite database, journal, upload spool, or object touches
disk. SQLite's SQL snapshot is portable to Python builds without serialize().
"""
from __future__ import annotations

import base64
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sqlite3
import threading
import time

CHUNK_BYTES = 8 * 1024
PAGE_SIZE = 20
# A traveling clipboard, not a bulk-file transport. Keep perimeter limits intact.
MAX_OBJECT_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ITEMS = 1000
UPLOAD_TTL = 300
_ID = re.compile(r"^[a-f0-9]{32}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")


class DropError(ValueError):
    """Public, deliberately content-free protocol error."""
    def __init__(self, message, *, reason=None):
        super().__init__(message)
        self.reason = reason


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise DropError("Numeric parameter is out of range")
    return value


def identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise DropError("Invalid object identifier")
    return value


def bounded_text(value, limit):
    if (not isinstance(value, str) or len(value.encode("utf-8")) > limit or "\x00" in value
            or len(json.dumps(value, ensure_ascii=True)) > limit + 2):
        raise DropError("Text field is invalid or too long")
    return value


class DropStore:
    def __init__(self, persistence):
        self.persistence = persistence
        self.lock = threading.RLock()
        self.uploads = {}
        self.cache = OrderedDict()
        self.cleanup_error = None
        self.cleanup_errno = None
        self._closed = False
        # A shared persistent_state profile must not produce competing writers.
        self._lease = open(persistence._encrypted_state_root / ".writer.lock", "a+b")
        try:
            os.chmod(self._lease.name, 0o600)
            if os.name == "nt":
                import msvcrt
                self._lease.seek(0)
                if not self._lease.read(1):
                    self._lease.write(b"0")
                    self._lease.flush()
                self._lease.seek(0)
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            self._lease.close()
            raise DropError("Storage is already in use or its writer lock is unavailable", reason="IO_FAILURE") from None
        try:
            self.db = sqlite3.connect(":memory:", check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA temp_store=MEMORY")
            saved = persistence.load_encrypted_state("catalog")
            if saved is None:
                self.db.executescript("""
                    CREATE TABLE state (revision INTEGER NOT NULL);
                    INSERT INTO state VALUES (0);
                    CREATE TABLE garbage (id TEXT PRIMARY KEY);
                    CREATE TABLE objects (
                        id TEXT PRIMARY KEY, created TEXT NOT NULL, kind TEXT NOT NULL,
                        title TEXT NOT NULL, filename TEXT NOT NULL, notes TEXT NOT NULL,
                        size INTEGER NOT NULL, sha256 TEXT NOT NULL, owner TEXT NOT NULL);
                """)
                self._save_catalog()
            else:
                if not isinstance(saved, dict) or saved.get("format") != "sqlite-sql-v1":
                    raise DropError("Unsupported encrypted catalogue format; storage was not reset", reason="INVALID_CONFIGURATION")
                self.db.executescript(saved["sql"])
                if self.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise DropError("Encrypted catalogue integrity check failed", reason="IO_FAILURE")
                self.db.execute("SELECT revision FROM state").fetchone()[0]
                self.db.execute("SELECT id, created, kind, title, filename, notes, size, sha256, owner FROM objects LIMIT 1")
        except Exception:
            self.close()
            raise

    def _save_catalog(self):
        self.persistence.save_encrypted_state(
            "catalog", {"format": "sqlite-sql-v1", "sql": "\n".join(self.db.iterdump())})

    def _guard(self):
        if self._closed:
            raise DropError("Storage is closed", reason="IO_FAILURE")

    def _row(self, object_id):
        return self.db.execute("SELECT * FROM objects WHERE id=?", (identifier(object_id),)).fetchone()

    @staticmethod
    def _public(row, *, notes=True):
        result = {k: row[k] for k in ("id", "created", "kind", "title", "filename", "size", "sha256")}
        if notes:
            result["notes"] = row["notes"]
        return result

    def maintain(self):
        with self.lock:
            now = time.monotonic()
            self.uploads = {k: v for k, v in self.uploads.items() if v["expires"] > now}
            self.cache = OrderedDict((k, v) for k, v in self.cache.items() if v[0] > now)

    def listing(self, before=None):
        with self.lock:
            self._guard()
            rows = self.db.execute(
                "SELECT * FROM objects WHERE rowid < ? ORDER BY rowid DESC LIMIT ?",
                (integer(before, 1, 2**63-1) if before is not None else 2**63-1, PAGE_SIZE+1)).fetchall()
            page = rows[:PAGE_SIZE]
            cursor = None
            if len(rows) > PAGE_SIZE:
                cursor = self.db.execute("SELECT rowid FROM objects WHERE id=?", (page[-1]["id"],)).fetchone()[0]
            count, size = self.db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM objects").fetchone()
            return {"entries": [self._public(row, notes=False) for row in page],
                    "revision": self.db.execute("SELECT revision FROM state").fetchone()[0],
                    "next_before": cursor, "total_items": count, "total_bytes": size,
                    "pending_deletions": self.db.execute("SELECT COUNT(*) FROM garbage").fetchone()[0],
                    "max_object_bytes": MAX_OBJECT_BYTES, "chunk_bytes": CHUNK_BYTES}

    def begin(self, owner, object_id, kind, title, filename, notes, size, sha256):
        identifier(object_id)
        if kind not in ("text", "file"):
            raise DropError("Only pasted text and regular files are supported")
        title, notes = bounded_text(title, 256), bounded_text(notes, 4096)
        filename = bounded_text(filename, 255)
        # Filenames are display labels only, never server paths. Refuse path
        # separators and platform special names before a client can export.
        if kind == "file" and (not filename or any(c in filename for c in '/\\:\x00')
                               or filename in (".", "..")):
            raise DropError("A plain filename is required")
        integer(size, 0, MAX_OBJECT_BYTES)
        if not isinstance(sha256, str) or not _SHA.fullmatch(sha256):
            raise DropError("A SHA-256 checksum is required")
        meta = dict(id=object_id, kind=kind, title=title, filename=filename,
                    notes=notes, size=size, sha256=sha256, owner=owner)
        with self.lock:
            self._guard()
            self.maintain()
            if self.db.execute("SELECT id FROM garbage WHERE id=?", (object_id,)).fetchone():
                raise DropError("Object identifier is pending deletion; start a new upload")
            row = self._row(object_id)
            if row:
                if any(row[k] != v for k, v in meta.items()):
                    raise DropError("Object identifier is already in use")
                return {"object_id": object_id, "offset": size, "committed": True}
            current = self.uploads.get(object_id)
            if current:
                if current["meta"] != meta:
                    raise DropError("Upload belongs to a different request")
                current["expires"] = time.monotonic() + UPLOAD_TTL
                return {"object_id": object_id, "offset": len(current["data"]), "committed": False}
            count, stored = self.db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM objects").fetchone()
            if count + len(self.uploads) >= MAX_ITEMS or len(self.uploads) >= 4:
                raise DropError("Inbox or concurrent upload limit reached", reason="RESOURCE_LIMIT")
            if stored + sum(u["meta"]["size"] for u in self.uploads.values()) + size > MAX_TOTAL_BYTES:
                raise DropError("Inbox storage quota reached", reason="RESOURCE_LIMIT")
            self.uploads[object_id] = {"meta": meta, "data": bytearray(), "expires": time.monotonic() + UPLOAD_TTL}
            return {"object_id": object_id, "offset": 0, "committed": False}

    def _upload(self, owner, object_id):
        self._guard()
        self.maintain()
        upload = self.uploads.get(identifier(object_id))
        if not upload or upload["meta"]["owner"] != owner:
            raise DropError("Upload expired or belongs to another connection")
        upload["expires"] = time.monotonic() + UPLOAD_TTL
        return upload

    def chunk(self, owner, object_id, offset, data):
        integer(offset, 0, MAX_OBJECT_BYTES)
        if not isinstance(data, str) or len(data) > 4 * ((CHUNK_BYTES + 2) // 3):
            raise DropError("Chunk is too large")
        try:
            block = base64.b64decode(data, validate=True)
        except ValueError:
            raise DropError("Invalid chunk encoding") from None
        if not block or len(block) > CHUNK_BYTES:
            raise DropError("Invalid chunk size")
        with self.lock:
            upload = self._upload(owner, object_id)
            target = upload["data"]
            if offset < len(target) and target[offset:offset+len(block)] == block:
                return {"offset": len(target)}  # Lost ACK: identical replay is safe.
            if offset != len(target) or offset + len(block) > upload["meta"]["size"]:
                raise DropError("Chunk offset or declared size mismatch")
            target.extend(block)
            return {"offset": len(target)}

    def commit(self, owner, object_id):
        with self.lock:
            self._guard()
            row = self._row(object_id)
            if row:
                if row["owner"] != owner:
                    raise DropError("Object belongs to a different upload")
                return {"entry": self._public(row)}
            upload = self._upload(owner, object_id)
            meta, data = upload["meta"], bytes(upload["data"])
            if len(data) != meta["size"] or hashlib.sha256(data).hexdigest() != meta["sha256"]:
                raise DropError("Incomplete upload or checksum mismatch; nothing was published")
            if meta["kind"] == "text":
                try:
                    data.decode("utf-8")
                except UnicodeError:
                    raise DropError("Pasted text must be UTF-8") from None
            # Object first, catalogue second: a crash can leave an encrypted
            # orphan but never a catalogue entry pointing to an unwritten object.
            self.persistence.save_encrypted_state(object_id, {
                "data": base64.b64encode(data).decode("ascii")}, directory="objects")
            try:
                self.db.execute("INSERT INTO objects VALUES (?,?,?,?,?,?,?,?,?)", (
                    object_id, datetime.now(timezone.utc).isoformat(), meta["kind"], meta["title"],
                    meta["filename"], meta["notes"], meta["size"], meta["sha256"], owner))
                self.db.execute("UPDATE state SET revision=revision+1")
                self._save_catalog()
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            del self.uploads[object_id]
            return {"entry": self._public(self._row(object_id))}

    def read(self, object_id, offset):
        integer(offset, 0, MAX_OBJECT_BYTES)
        with self.lock:
            self._guard()
            self.maintain()
            row = self._row(object_id)
            if not row:
                raise DropError("Object does not exist")
            if offset > row["size"]:
                raise DropError("Read offset exceeds object size")
            cached = self.cache.get(object_id)
            if cached:
                data = cached[1]
            else:
                saved = self.persistence.load_encrypted_state(object_id, directory="objects")
                data = base64.b64decode(saved["data"], validate=True)
                if len(data) != row["size"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                    raise DropError("Stored object failed integrity verification", reason="IO_FAILURE")
            self.cache[object_id] = (time.monotonic() + 60, data)
            self.cache.move_to_end(object_id)
            while len(self.cache) > 2:
                self.cache.popitem(last=False)
            block = data[offset:offset+CHUNK_BYTES]
            return {"entry": self._public(row), "offset": offset,
                    "data": base64.b64encode(block).decode("ascii"), "eof": offset+len(block) == len(data)}

    def cancel(self, owner, object_id):
        with self.lock:
            self._upload(owner, object_id)
            del self.uploads[object_id]
            return {}

    def delete(self, object_id):
        with self.lock:
            self._guard()
            row = self._row(object_id)
            if row:
                try:
                    self.db.execute("INSERT OR IGNORE INTO garbage VALUES (?)", (object_id,))
                    self.db.execute("DELETE FROM objects WHERE id=?", (object_id,))
                    self.db.execute("UPDATE state SET revision=revision+1")
                    self._save_catalog()
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    raise
            self.cache.pop(object_id, None)
            self.collect_garbage()
            pending = self.db.execute("SELECT id FROM garbage WHERE id=?", (object_id,)).fetchone()
            return {"deleted": True, "cleanup_pending": pending is not None}

    def collect_garbage(self):
        """Retry only operator-requested deletions; never purge arbitrary files."""
        with self.lock:
            self._guard()
            self.cleanup_error = None
            self.cleanup_errno = None
            rows = self.db.execute("SELECT id FROM garbage LIMIT 10").fetchall()
            for row in rows:
                try:
                    self.persistence.delete_encrypted_state(identifier(row[0]), directory="objects")
                    self.db.execute("DELETE FROM garbage WHERE id=?", (row[0],))
                    self._save_catalog()
                    self.db.commit()
                except Exception as exc:
                    self.db.rollback()
                    self.cleanup_error = type(exc).__name__
                    self.cleanup_errno = getattr(exc, "errno", None)
                    # Keep the encrypted deletion receipt for a later retry.
                    return

    def close(self):
        with self.lock:
            if self._closed:
                return
            self._closed = True
            self.uploads.clear()
            self.cache.clear()
            if hasattr(self, "db"):
                self.db.close()
            if not self._lease.closed:
                self._lease.close()
