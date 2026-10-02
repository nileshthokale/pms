"""Application authentication and two-role permission policy.

This module is the only source of truth for user roles and application
permissions. Ledger system roles in ``database.account_roles`` are unrelated.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Any

from database.connection import get_connection

ROLE_ADMIN = "ADMIN"
ROLE_PHARMACIST_STAFF = "PHARMACIST/STAFF"
USER_ROLES = (ROLE_ADMIN, ROLE_PHARMACIST_STAFF)

PERM_VIEW_MASTERS = "view_masters"
PERM_PURCHASE = "purchase"
PERM_SALES = "sales"
PERM_COUNTER_SALE = "counter_sale"
PERM_CREDIT_NOTE = "credit_note"
PERM_DEBIT_NOTE = "debit_note"
PERM_CUSTOMER_RECEIPT = "customer_receipt"
PERM_SUPPLIER_PAYMENT = "supplier_payment"
PERM_REPORTS = "reports"
PERM_PRINT_PDF = "print_pdf"
PERM_EDIT_TRANSACTIONS = "edit_transactions"
PERM_DELETE_TRANSACTIONS = "delete_transactions"
PERM_IMPORT_DATA = "import_data"
PERM_BACKUP = "backup"
PERM_RESTORE = "restore"
PERM_USER_MANAGEMENT = "user_management"
PERM_ROLE_ADMINISTRATION = "role_administration"
PERM_SECURITY_AUDIT = "security_audit"
PERM_PASSWORD_RESET_OTHERS = "password_reset_others"
PERM_DEACTIVATE_USERS = "deactivate_users"
PERM_FINANCIAL_YEAR_MANAGEMENT = "financial_year_management"
PERM_CATEGORY_MANAGEMENT = "category_management"

STAFF_PERMISSIONS = frozenset({
    PERM_VIEW_MASTERS, PERM_PURCHASE, PERM_SALES, PERM_COUNTER_SALE,
    PERM_CREDIT_NOTE, PERM_DEBIT_NOTE, PERM_CUSTOMER_RECEIPT,
    PERM_SUPPLIER_PAYMENT, PERM_REPORTS, PERM_PRINT_PDF,
})
ADMIN_PERMISSIONS = frozenset({
    PERM_VIEW_MASTERS, PERM_PURCHASE, PERM_SALES, PERM_COUNTER_SALE,
    PERM_CREDIT_NOTE, PERM_DEBIT_NOTE, PERM_CUSTOMER_RECEIPT,
    PERM_SUPPLIER_PAYMENT, PERM_REPORTS, PERM_PRINT_PDF,
    PERM_EDIT_TRANSACTIONS, PERM_DELETE_TRANSACTIONS, PERM_IMPORT_DATA,
    PERM_BACKUP, PERM_RESTORE, PERM_USER_MANAGEMENT,
    PERM_ROLE_ADMINISTRATION, PERM_SECURITY_AUDIT,
    PERM_PASSWORD_RESET_OTHERS, PERM_DEACTIVATE_USERS,
    PERM_FINANCIAL_YEAR_MANAGEMENT,
    PERM_CATEGORY_MANAGEMENT,
})
PERMISSIONS = {
    ROLE_ADMIN: ADMIN_PERMISSIONS,
    ROLE_PHARMACIST_STAFF: STAFF_PERMISSIONS,
}
MENU_PERMISSIONS = {
    "Account Roles": PERM_ROLE_ADMINISTRATION,
    "Import Data": PERM_IMPORT_DATA,
    "Backup & Restore": PERM_BACKUP,
    "User Management": PERM_USER_MANAGEMENT,
    "User Master": PERM_USER_MANAGEMENT,
    "Financial Year": PERM_FINANCIAL_YEAR_MANAGEMENT,
    "Category Master": PERM_CATEGORY_MANAGEMENT,
}

PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 240_000


class AuthenticationError(ValueError):
    """Raised when authentication or account administration is refused."""


class PermissionDenied(AuthenticationError):
    """Raised when the active user lacks a named permission."""


def ensure_auth_schema() -> None:
    conn = get_connection()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS app_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_login_at TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS auth_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            success INTEGER NOT NULL,
            details TEXT DEFAULT ''
        )""")
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise AuthenticationError("Password must contain at least 8 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(PBKDF2_ALGORITHM, password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != f"pbkdf2_{PBKDF2_ALGORITHM}":
            return False
        digest = hashlib.pbkdf2_hmac(PBKDF2_ALGORITHM, password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (AttributeError, TypeError, ValueError):
        return False


def _validate_role(role: str) -> str:
    if role not in USER_ROLES:
        raise AuthenticationError("Role is not supported.")
    return role


def _audit(username: str, action: str, success: bool, details: str = "") -> None:
    conn = get_connection()
    try:
        conn.execute("INSERT INTO auth_audit_log (timestamp, username, action, success, details) VALUES (?, ?, ?, ?, ?)", (_now(), username, action, int(success), details))
        conn.commit()
    finally:
        conn.close()


def list_users() -> list[dict[str, Any]]:
    ensure_auth_schema()
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, username, role, is_active, created_at, updated_at, last_login_at FROM app_users ORDER BY username").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_user(username: str) -> dict[str, Any] | None:
    ensure_auth_schema()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM app_users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def user_count() -> int:
    return len(list_users())


def active_admin_count(conn=None) -> int:
    own = conn is None
    conn = conn or get_connection()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM app_users WHERE role = ? AND is_active = 1", (ROLE_ADMIN,)).fetchone()[0])
    finally:
        if own:
            conn.close()


def create_first_admin(username: str, password: str) -> dict[str, Any]:
    ensure_auth_schema()
    username = username.strip()
    if not username:
        raise AuthenticationError("Username is required.")
    conn = get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM app_users").fetchone()[0]:
            raise AuthenticationError("First ADMIN already exists.")
        now = _now()
        cursor = conn.execute("INSERT INTO app_users (username, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (username, hash_password(password), ROLE_ADMIN, now, now))
        conn.commit()
        _audit(username, "first_admin_created", True)
        return {"id": cursor.lastrowid, "username": username, "role": ROLE_ADMIN, "is_active": 1}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    ensure_auth_schema()
    user = get_user(username.strip())
    if not user or not user["is_active"] or not verify_password(password, user["password_hash"]):
        _audit(username.strip(), "login", False, "invalid credentials or inactive account")
        return None
    conn = get_connection()
    try:
        conn.execute("UPDATE app_users SET last_login_at = ?, updated_at = ? WHERE id = ?", (_now(), _now(), user["id"]))
        conn.commit()
    finally:
        conn.close()
    _audit(user["username"], "login", True)
    return {key: user[key] for key in ("id", "username", "role", "is_active")}


def _require_actor(actor: dict[str, Any] | None, permission: str) -> None:
    if not actor or not has_permission(actor, permission):
        raise PermissionDenied(f"Permission required: {permission}")


def has_permission(user: dict[str, Any] | None, permission: str) -> bool:
    return bool(user and user.get("is_active") and permission in PERMISSIONS.get(user.get("role"), frozenset()))


def create_user(actor: dict[str, Any], username: str, password: str, role: str) -> dict[str, Any]:
    _require_actor(actor, PERM_USER_MANAGEMENT)
    role = _validate_role(role)
    username = username.strip()
    if not username:
        raise AuthenticationError("Username is required.")
    ensure_auth_schema()
    now = _now()
    conn = get_connection()
    try:
        cursor = conn.execute("INSERT INTO app_users (username, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (username, hash_password(password), role, now, now))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise AuthenticationError("Could not create user.") from exc
    finally:
        conn.close()
    _audit(actor["username"], "user_created", True, username)
    return {"id": cursor.lastrowid, "username": username, "role": role, "is_active": 1}


def change_role(actor: dict[str, Any], user_id: int, role: str) -> None:
    _require_actor(actor, PERM_ROLE_ADMINISTRATION)
    role = _validate_role(role)
    ensure_auth_schema()
    conn = get_connection()
    try:
        row = conn.execute("SELECT username, role, is_active FROM app_users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthenticationError("User not found.")
        if row["role"] == ROLE_ADMIN and role != ROLE_ADMIN and row["is_active"] and active_admin_count(conn) <= 1:
            raise AuthenticationError("At least one active ADMIN must remain.")
        conn.execute("UPDATE app_users SET role = ?, updated_at = ? WHERE id = ?", (role, _now(), user_id)); conn.commit()
    finally:
        conn.close()
    _audit(actor["username"], "role_changed", True, str(user_id))


def set_user_active(actor: dict[str, Any], user_id: int, active: bool) -> None:
    _require_actor(actor, PERM_DEACTIVATE_USERS)
    active = bool(active)
    ensure_auth_schema()
    conn = get_connection()
    try:
        row = conn.execute("SELECT username, role, is_active FROM app_users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthenticationError("User not found.")
        if row["role"] == ROLE_ADMIN and row["is_active"] and not active and active_admin_count(conn) <= 1:
            raise AuthenticationError("At least one active ADMIN must remain.")
        conn.execute("UPDATE app_users SET is_active = ?, updated_at = ? WHERE id = ?", (int(active), _now(), user_id)); conn.commit()
    finally:
        conn.close()
    _audit(actor["username"], "user_activation_changed", True,
           f"{row['username']}:{'activated' if active else 'deactivated'}")


def reset_password(actor: dict[str, Any], user_id: int, password: str) -> None:
    _require_actor(actor, PERM_PASSWORD_RESET_OTHERS)
    ensure_auth_schema()
    conn = get_connection()
    try:
        row = conn.execute("SELECT username FROM app_users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthenticationError("User not found.")
        conn.execute("UPDATE app_users SET password_hash = ?, updated_at = ? WHERE id = ?", (hash_password(password), _now(), user_id)); conn.commit()
    finally:
        conn.close()
    _audit(actor["username"], "password_reset", True, str(user_id))


def get_audit_log(limit: int = 100) -> list[dict[str, Any]]:
    ensure_auth_schema()
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM auth_audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    finally:
        conn.close()


class AuthSession:
    def __init__(self):
        self.user: dict[str, Any] | None = None

    def login(self, username: str, password: str) -> bool:
        self.user = authenticate(username, password)
        return self.user is not None

    def logout(self) -> None:
        if self.user:
            _audit(self.user["username"], "logout", True)
        self.user = None

    def has_permission(self, permission: str) -> bool:
        return has_permission(self.user, permission)

    def require(self, permission: str) -> None:
        _require_actor(self.user, permission)


session = AuthSession()

__all__ = [
    "ROLE_ADMIN", "ROLE_PHARMACIST_STAFF", "USER_ROLES", "PERMISSIONS", "STAFF_PERMISSIONS", "ADMIN_PERMISSIONS",
    "PERM_VIEW_MASTERS", "PERM_PURCHASE", "PERM_SALES", "PERM_COUNTER_SALE", "PERM_CREDIT_NOTE", "PERM_DEBIT_NOTE",
    "PERM_CUSTOMER_RECEIPT", "PERM_SUPPLIER_PAYMENT", "PERM_REPORTS", "PERM_PRINT_PDF", "PERM_EDIT_TRANSACTIONS",
    "PERM_DELETE_TRANSACTIONS", "PERM_IMPORT_DATA", "PERM_BACKUP", "PERM_RESTORE", "PERM_USER_MANAGEMENT",
    "PERM_ROLE_ADMINISTRATION", "PERM_SECURITY_AUDIT", "PERM_PASSWORD_RESET_OTHERS", "PERM_DEACTIVATE_USERS",
    "PERM_FINANCIAL_YEAR_MANAGEMENT",
    "PERM_CATEGORY_MANAGEMENT",
    "AuthenticationError", "PermissionDenied", "ensure_auth_schema", "hash_password", "verify_password",
    "create_first_admin", "authenticate", "has_permission", "create_user", "change_role", "set_user_active",
    "reset_password", "list_users", "get_user", "user_count", "active_admin_count", "get_audit_log", "AuthSession", "session",
]
