"""
auth.py — authentication for the hosted FSM RFP Evaluation Agent.

Owns the user store (hashed passwords in human-inspectable JSON, one map keyed by
email), password verification/change, Flask session helpers, and the require_auth
decorator. Consistent with the project ethos: no DB, atomic JSON writes, secrets
never written in plaintext. API/data behaviour is unchanged — this only gates it.
"""
from __future__ import annotations

import os
import json
import secrets
import logging
import tempfile
from functools import wraps
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable

from flask import session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

_log = logging.getLogger("auth")

TEMP_PASSWORD = "ServiceLogic2026!"
MIN_PASSWORD_LEN = 8

_HERE = os.path.dirname(os.path.abspath(__file__))

# Seed roster: (email, display name, org). Emails resolved via Outlook 2026-06-30.
_SEED_ACCOUNTS = [
    ("fasbeck@ssaandco.com", "Fred Asbeck", "SSA"),
    ("nkramer@ssaandco.com", "Nick Kramer", "SSA"),
    ("jbrown@ssaandco.com", "Jeff Brown", "SSA"),
    ("chagood@ssaandco.com", "Camp Hagood", "SSA"),
    ("sadiwidjaja@ssaandco.com", "Samantha Adiwidjaja", "SSA"),
    ("ksoviero@baincapital.com", "Kim Soviero", "Bain Capital"),
    ("eashworth@baincapital.com", "Emily Ashworth", "Bain Capital"),
    ("demo@servicelogic-rfp.local", "Demo User", "Demo"),
]


def _users_path() -> str:
    """Resolved at call time so tests (and Render) can point USERS_FILE elsewhere."""
    return os.environ.get("USERS_FILE", os.path.join(_HERE, "data", "store", "users.json"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: str, data: Dict[str, Any]) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _seed_defaults() -> Dict[str, Dict[str, Any]]:
    users: Dict[str, Dict[str, Any]] = {}
    for email, name, org in _SEED_ACCOUNTS:
        e = email.lower()
        users[e] = {
            "email": e,
            "name": name,
            "org": org,
            # Pin PBKDF2 explicitly: Werkzeug 3.x defaults to scrypt, which is
            # non-deterministic across hosts (OpenSSL memory-cost) and breaks the test.
            "password_hash": generate_password_hash(TEMP_PASSWORD, method="pbkdf2"),
            "must_change": True,
            "updated_at": _now(),
        }
    return users


def load_users() -> Dict[str, Dict[str, Any]]:
    """Load the {email: record} map. If the file is missing, seed it and write once.
    If it exists, existing records WIN (changed passwords are never clobbered) — but
    any roster member in _SEED_ACCOUNTS not yet in the file is added with the temp
    password, so a teammate can be provisioned by extending _SEED_ACCOUNTS + redeploying
    without resetting anyone. A corrupt/empty file logs a warning and falls back to
    in-memory seeds — never crashes."""
    path = _users_path()
    if not os.path.exists(path):
        users = _seed_defaults()
        try:
            _atomic_write(path, users)
        except Exception as e:
            _log.warning("could not write seeded users file %s: %s", path, e)
        return users
    try:
        with open(path, "r", encoding="utf-8") as f:
            users = json.load(f)
        if not isinstance(users, dict) or not users:
            raise ValueError("users file empty or not an object")
    except Exception as e:
        _log.warning("unreadable users file %s: %s; using in-memory seeds", path, e)
        return _seed_defaults()
    # Add-only merge: provision new roster members without touching existing records.
    added = False
    for e, rec in _seed_defaults().items():
        if e not in users:
            users[e] = rec
            added = True
    if added:
        try:
            _atomic_write(path, users)
        except Exception as e:
            _log.warning("could not persist newly seeded accounts to %s: %s", path, e)
    return users


def save_users(users: Dict[str, Dict[str, Any]]) -> None:
    _atomic_write(_users_path(), users)


def public_view(record: Dict[str, Any]) -> Dict[str, Any]:
    """Safe-to-return projection. Never includes password_hash."""
    return {k: record.get(k) for k in ("name", "email", "org", "must_change")}


def verify(email: str, password: str) -> Optional[Dict[str, Any]]:
    if not email or not password:
        return None
    rec = load_users().get(email.strip().lower())
    if rec and check_password_hash(rec.get("password_hash", ""), password):
        return rec
    return None


def set_password(email: str, new_password: str) -> None:
    if not new_password or len(new_password) < MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    users = load_users()
    e = (email or "").strip().lower()
    rec = users.get(e)
    if not rec:
        raise ValueError("Unknown user.")
    rec["password_hash"] = generate_password_hash(new_password, method="pbkdf2")
    rec["must_change"] = False
    rec["updated_at"] = _now()
    users[e] = rec
    save_users(users)


def get_secret_key() -> str:
    """Flask SECRET_KEY: env var, else a key file next to the users file (generated
    once and reused so sessions survive restarts), else an ephemeral key."""
    env = os.environ.get("SESSION_SECRET")
    if env:
        return env
    key_path = os.path.join(os.path.dirname(_users_path()), "secret_key")
    try:
        if os.path.exists(key_path):
            with open(key_path, "r", encoding="utf-8") as f:
                k = f.read().strip()
            if k:
                return k
        k = secrets.token_hex(32)
        # Atomic write (temp + os.replace), consistent with the user store: a crash
        # mid-write must not leave a truncated key that silently invalidates sessions.
        d = os.path.dirname(key_path)
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(k)
            os.replace(tmp, key_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return k
    except Exception as e:
        _log.warning("could not persist secret key (%s); using ephemeral key", e)
        return secrets.token_hex(32)


# ---- session helpers (used by app.py; exercised in Task 2) ----------------- #
def login_user(record: Dict[str, Any]) -> None:
    session.permanent = True
    session["email"] = record["email"]


def logout_user() -> None:
    session.pop("email", None)


def current_user() -> Optional[Dict[str, Any]]:
    email = session.get("email")
    if not email:
        return None
    return load_users().get(email)


def require_auth(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return jsonify({"error": "auth required"}), 401
        return fn(*args, **kwargs)
    return wrapper
