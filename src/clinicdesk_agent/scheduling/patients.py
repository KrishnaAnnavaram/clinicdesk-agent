"""Minimal patient identity: a handle plus a salted scrypt passcode hash.

The scheduling service identifies patients only by ``patient_id``; the chat
session obtains that id by authenticating here, never from the language model.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime

from clinicdesk_agent.db import Database, transaction
from clinicdesk_agent.scheduling.errors import AuthError
from clinicdesk_agent.scheduling.models import Patient, to_db_time

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
HANDLE_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,31}")
MIN_PASSCODE_LENGTH = 6


def hash_passcode(passcode: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(passcode.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_passcode(passcode: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(passcode.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                   n=int(n), r=int(r), p=int(p), dklen=len(digest_hex) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest_hex)


def normalise_handle(handle: str) -> str:
    value = handle.strip().lower()
    if not HANDLE_RE.fullmatch(value):
        raise AuthError("handle must be 3-32 characters: letters, digits, '.', '_' or '-'")
    return value


class PatientRegistry:
    def __init__(self, db: Database) -> None:
        self.db = db

    def register(self, handle: str, passcode: str, *, now: datetime | None = None) -> Patient:
        handle = normalise_handle(handle)
        if len(passcode) < MIN_PASSCODE_LENGTH:
            raise AuthError(f"passcode must be at least {MIN_PASSCODE_LENGTH} characters")
        created = to_db_time(now or datetime.now())
        with self.db.writer() as conn, transaction(conn):
            if conn.execute("SELECT 1 FROM patients WHERE handle = ?", (handle,)).fetchone():
                raise AuthError("that handle is already registered")
            cur = conn.execute(
                "INSERT INTO patients (handle, passcode_hash, created_at) VALUES (?, ?, ?)",
                (handle, hash_passcode(passcode), created),
            )
            return Patient(patient_id=int(cur.lastrowid), handle=handle)

    def authenticate(self, handle: str, passcode: str) -> Patient:
        try:
            handle = normalise_handle(handle)
        except AuthError:
            raise AuthError("invalid handle or passcode") from None
        with self.db.reader() as conn:
            row = conn.execute("SELECT patient_id, passcode_hash FROM patients WHERE handle = ?", (handle,)).fetchone()
        if row is None or not verify_passcode(passcode, row["passcode_hash"]):
            raise AuthError("invalid handle or passcode")
        return Patient(patient_id=int(row["patient_id"]), handle=handle)
