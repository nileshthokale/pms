"""Safe master-data import service for CSV and XLSX files.

This module deliberately works only with the SQLite connection returned by
``database.connection``.  It does not know about, or connect to, any legacy
database.  Preview and validation use read-only operations; writes are made
through one transaction owned by this service.
"""

from __future__ import annotations

import csv
import io
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from database.connection import get_connection, init_database

try:  # Optional at runtime; CSV remains fully supported without it.
    import openpyxl
except ImportError:  # pragma: no cover - exercised in dependency-limited installs
    openpyxl = None


MASTER_TYPES = ("company", "unit", "drug", "supplier", "customer", "doctor", "item")
DISPLAY_NAMES = {name: name.title() for name in MASTER_TYPES}

FIELD_DEFINITIONS: dict[str, dict[str, dict[str, Any]]] = {
    "company": {"company_name": {"required": True}, "short_name": {"required": False}},
    "unit": {"unit_name": {"required": True}},
    "drug": {"drug_name": {"required": True}},
    "supplier": {
        "supplier_name": {"required": True}, "sales_tax_no": {}, "vat_or_tin": {},
        "city": {}, "contact_person": {}, "contact_no": {}, "address": {}, "state": {},
        "discount": {"type": "number"}, "credit_limit": {"type": "number"},
        "credit_period": {"type": "integer"}, "vat_tin": {}, "opening_balance": {"type": "number"},
    },
    "customer": {
        "customer_name": {"required": True}, "city": {}, "contact_person": {}, "contact_no": {},
        "address": {}, "state": {}, "discount": {"type": "number"},
        "credit_limit": {"type": "number"}, "credit_period": {"type": "integer"},
        "opening_balance": {"type": "number"},
    },
    "doctor": {"doctor_name": {"required": True}, "city": {}, "specialty": {}, "phone_no": {}},
    "item": {
        "item_name": {"required": True}, "unit": {"reference": "unit"},
        "company": {"reference": "company"}, "category": {"reference": "category"},
        "pack_size": {}, "tax_structure": {},
        "discount": {"type": "number"}, "mrp": {"type": "number"}, "rate": {"type": "number"},
        "reorder_stock_level": {"type": "integer"}, "scheduled": {"type": "boolean"},
        "location": {}, "pathy": {}, "dpco": {}, "ingredients": {},
    },
}

ALIASES = {
    "company_name": ("company name", "company", "name"), "short_name": ("short name", "short"),
    "unit_name": ("unit name", "unit"), "drug_name": ("drug name", "drug"),
    "supplier_name": ("supplier name", "supplier"), "customer_name": ("customer name", "customer"),
    "doctor_name": ("doctor name", "doctor"), "sales_tax_no": ("sales tax no", "sales tax number"),
    "vat_or_tin": ("vat/tin", "vat or tin", "vat tin"), "vat_tin": ("vat tin no",),
    "contact_no": ("contact no", "contact number", "phone"), "phone_no": ("phone no", "phone number"),
    "contact_person": ("contact person",), "credit_period": ("credit period",),
    "credit_limit": ("credit limit",), "opening_balance": ("opening balance",),
    "item_name": ("item name", "item"), "pack_size": ("pack size",),
    "tax_structure": ("tax structure",), "reorder_stock_level": ("reorder stock level", "reorder level"),
    "scheduled": ("scheduled",), "location": ("location",), "pathy": ("pathy",),
    "dpco": ("dpco",), "ingredients": ("ingredients", "ingredient"),
    "category": ("category", "category name"),
}

TABLE_KEYS = {
    "company": ("companies", "company_name", "short_name"), "unit": ("units", "unit_name"),
    "drug": ("drugs", "drug_name"), "supplier": ("suppliers", "supplier_name"),
    "customer": ("customers", "customer_name"), "doctor": ("doctors", "doctor_name"),
    "category": ("categories", "category_name"),
    "item": ("items", "item_name"),
}


class ImportErrorDetail(ValueError):
    """Raised for a user-correctable import problem."""


def normalize_value(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\ufeff", "").strip().split())


def _header_key(value: Any) -> str:
    return " ".join(normalize_value(value).casefold().replace("_", " ").split())


def _canonical_master(master_type: str) -> str:
    value = _header_key(master_type).rstrip("s")
    if value not in MASTER_TYPES:
        raise ImportErrorDetail(f"Unsupported master type: {master_type}")
    return value


def read_csv(path: str | os.PathLike[str]) -> dict[str, Any]:
    path = str(path)
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportErrorDetail("CSV must be UTF-8 encoded (UTF-8 BOM is supported).") from exc
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as exc:
        raise ImportErrorDetail(f"Malformed CSV: {exc}") from exc
    if not rows:
        return {"headers": [], "rows": [], "sheet": None, "path": path}
    headers = [normalize_value(cell) for cell in rows[0]]
    width = len(headers)
    data = []
    for number, row in enumerate(rows[1:], 2):
        if not any(normalize_value(cell) for cell in row):
            continue
        if len(row) != width:
            data.append({"__row__": number, "__malformed__": f"Expected {width} columns, found {len(row)}"})
        else:
            data.append({header: cell for header, cell in zip(headers, row)})
    return {"headers": headers, "rows": data, "sheet": None, "path": path}


def read_excel(path: str | os.PathLike[str], sheet: str | None = None) -> dict[str, Any] | dict[str, list[str]]:
    if openpyxl is None:
        raise ImportErrorDetail("XLSX support requires the installed openpyxl package.")
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ImportErrorDetail(f"Unable to read workbook: {exc}") from exc
    try:
        names = workbook.sheetnames
        if sheet is None:
            return {"sheets": names}
        if sheet not in names:
            raise ImportErrorDetail(f"Worksheet not found: {sheet}")
        values = workbook[sheet].iter_rows(values_only=True)
        first = next(values, None)
        if first is None:
            return {"headers": [], "rows": [], "sheet": sheet, "path": str(path)}
        headers = [normalize_value(cell) for cell in first]
        data = []
        width = len(headers)
        for number, row in enumerate(values, 2):
            values_row = list(row)
            if not any(normalize_value(cell) for cell in values_row):
                continue
            if len(values_row) != width:
                data.append({"__row__": number, "__malformed__": f"Expected {width} columns, found {len(values_row)}"})
            else:
                data.append({header: cell for header, cell in zip(headers, values_row)})
        return {"headers": headers, "rows": data, "sheet": sheet, "path": str(path)}
    finally:
        workbook.close()


def inspect_file(path: str | os.PathLike[str], sheet: str | None = None) -> dict[str, Any]:
    suffix = Path(path).suffix.casefold()
    if suffix == ".csv":
        return read_csv(path)
    if suffix == ".xlsx":
        return read_excel(path, sheet)
    if suffix == ".xls":
        raise ImportErrorDetail(".xls is not supported safely; save the workbook as .xlsx or CSV.")
    raise ImportErrorDetail("Only .csv and .xlsx files are supported.")


def detect_columns(headers: Iterable[str], master_type: str) -> dict[str, str]:
    master = _canonical_master(master_type)
    normalized = {_header_key(header): header for header in headers}
    result = {}
    for field in FIELD_DEFINITIONS[master]:
        candidates = (_header_key(field),) + tuple(_header_key(alias) for alias in ALIASES.get(field, ()))
        match = next((normalized[key] for key in candidates if key in normalized), None)
        if match:
            result[match] = field
    return result


def _issue(row_number: int, field: str, value: Any, message: str, severity: str = "error") -> dict[str, Any]:
    return {"row": row_number, "field": field, "value": normalize_value(value), "message": message, "severity": severity}


def _parse_value(value: Any, definition: dict[str, Any]) -> Any:
    text = normalize_value(value)
    kind = definition.get("type")
    if not text:
        return 0 if kind in ("number", "integer") else False if kind == "boolean" else ""
    if kind == "number":
        try:
            return float(text.replace(",", ""))
        except ValueError as exc:
            raise ValueError("must be a number") from exc
    if kind == "integer":
        try:
            parsed = float(text)
            if not parsed.is_integer():
                raise ValueError
            return int(parsed)
        except ValueError as exc:
            raise ValueError("must be an integer") from exc
    if kind == "boolean":
        if text.casefold() in {"true", "yes", "1", "y"}:
            return "Yes"
        if text.casefold() in {"false", "no", "0", "n"}:
            return "No"
        raise ValueError("must be true/false, yes/no, or 1/0")
    return text


def _mapped_rows(data: dict[str, Any], mapping: dict[str, str]) -> list[dict[str, Any]]:
    output = []
    for index, source in enumerate(data.get("rows", []), 2):
        if "__malformed__" in source:
            output.append({"__row__": source.get("__row__", index), "__malformed__": source["__malformed__"]})
            continue
        row = {"__row__": source.get("__row__", index)}
        for source_name, target in mapping.items():
            row[target] = source.get(source_name, "")
        output.append(row)
    return output


def _lookup(conn: sqlite3.Connection, master: str, value: str) -> sqlite3.Row | None:
    table, key = TABLE_KEYS[master][:2]
    return conn.execute(f"SELECT id, {key} FROM {table} WHERE lower(trim({key})) = lower(trim(?))", (value,)).fetchone()


def validate_rows(master_type: str, data: dict[str, Any], mapping: dict[str, str] | None = None, *, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    master = _canonical_master(master_type)
    mapping = mapping or detect_columns(data.get("headers", []), master)
    own_conn = conn is None
    conn = conn or get_connection()
    issues: list[dict[str, Any]] = []
    valid_rows: list[dict[str, Any]] = []
    duplicate_rows: list[int] = []
    seen: set[str] = set()
    try:
        for row in _mapped_rows(data, mapping):
            number = row["__row__"]
            if "__malformed__" in row:
                issues.append(_issue(number, "", "", row["__malformed__"]))
                continue
            parsed = {"__row__": number}
            parsed["__mapped_fields"] = set(mapping.values())
            row_errors = 0
            for field, definition in FIELD_DEFINITIONS[master].items():
                value = row.get(field, "")
                if definition.get("required") and not normalize_value(value):
                    issues.append(_issue(number, field, value, "Required value is missing")); row_errors += 1; continue
                try:
                    parsed[field] = _parse_value(value, definition)
                except ValueError as exc:
                    issues.append(_issue(number, field, value, str(exc))); row_errors += 1
            key_field = TABLE_KEYS[master][1]
            identity = normalize_value(row.get(key_field, "")).casefold()
            if identity and identity in seen:
                duplicate_rows.append(number); row["__duplicate"] = True
                issues.append(_issue(number, key_field, row.get(key_field), "Duplicate row in file", "warning"))
            seen.add(identity)
            if master == "item":
                for field, reference in (("company", "company"), ("unit", "unit"), ("category", "category")):
                    ref = normalize_value(row.get(field, ""))
                    if ref and not _lookup(conn, reference, ref):
                        issues.append(_issue(number, field, ref, f"Referenced {reference} does not exist")); row_errors += 1
                    elif ref and reference == "category":
                        category = _lookup(conn, reference, ref)
                        if category and not conn.execute("SELECT is_active FROM categories WHERE id = ?", (category["id"],)).fetchone()["is_active"]:
                            issues.append(_issue(number, field, ref, "Referenced category is inactive")); row_errors += 1
                ingredients = [part.strip() for part in normalize_value(row.get("ingredients", "")).replace(";", ",").split(",") if part.strip()]
                for ingredient in ingredients:
                    if not _lookup(conn, "drug", ingredient):
                        issues.append(_issue(number, "ingredients", ingredient, "Referenced drug does not exist")); row_errors += 1
            if row_errors == 0:
                existing = _lookup(conn, master, normalize_value(row.get(key_field, "")))
                parsed["__existing_id"] = existing["id"] if existing else None
                parsed["__duplicate"] = row.get("__duplicate", False)
                valid_rows.append(parsed)
        return {"master_type": master, "mapping": mapping, "rows": valid_rows, "issues": issues,
                "total_rows": len(data.get("rows", [])), "valid_rows": len(valid_rows),
                "invalid_rows": sum(1 for issue in issues if issue["severity"] == "error"),
                "duplicate_rows": duplicate_rows,
                "unmapped_columns": [h for h in data.get("headers", []) if h not in mapping]}
    finally:
        if own_conn:
            conn.close()


def preview_import(master_type: str, data: dict[str, Any], mapping: dict[str, str] | None = None) -> dict[str, Any]:
    result = validate_rows(master_type, data, mapping)
    result["sample_rows"] = data.get("rows", [])[:5]
    result["warnings"] = [issue for issue in result["issues"] if issue["severity"] == "warning"]
    result["missing_required_fields"] = [issue for issue in result["issues"] if "Required" in issue["message"]]
    return result


def _insert_ledger(conn: sqlite3.Connection, name: str, group: str, values: dict[str, Any], opening: float) -> int:
    ledger_name = f"{group} - {name}"
    existing = conn.execute("SELECT id FROM account_ledgers WHERE ledger_name = ?", (ledger_name,)).fetchone()
    if existing:
        return existing["id"]
    cursor = conn.execute("""INSERT INTO account_ledgers
        (ledger_name, account_group, opening_balance, opening_balance_type,
         credit_limit, credit_period, address, city, state, contact_person, contact_no)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
        ledger_name, group, abs(opening), "Debit" if group == "Sundry Debtors" and opening >= 0 else "Credit",
        values.get("credit_limit", 0), values.get("credit_period", 0), values.get("address", ""),
        values.get("city", ""), values.get("state", ""), values.get("contact_person", ""), values.get("contact_no", "")))
    return cursor.lastrowid


def _write_row(conn: sqlite3.Connection, master: str, row: dict[str, Any]) -> int:
    values = {key: value for key, value in row.items() if not key.startswith("__")}
    if master == "company":
        values["short_name"] = values.get("short_name") or values["company_name"]
    if master == "item":
        for field, reference in (("company", "company"), ("unit", "unit"), ("category", "category")):
            ref = values.pop(field, "")
            values[f"{reference}_id"] = _lookup(conn, reference, ref)["id"] if ref else None
        # An older import file has no Category column.  On updates it must not
        # accidentally erase a category selected later in Item Master.
        if "category" not in row.get("__mapped_fields", set()):
            values.pop("category_id", None)
        ingredients = [part.strip() for part in normalize_value(values.pop("ingredients", "")).replace(";", ",").split(",") if part.strip()]
    if master in ("supplier", "customer"):
        opening = values.get("opening_balance", 0)
        ledger_id = _insert_ledger(conn, values[f"{master}_name"], "Sundry Creditors" if master == "supplier" else "Sundry Debtors", values, opening)
        values["ledger_id"] = ledger_id
    table, key = TABLE_KEYS[master][:2]
    existing = _lookup(conn, master, values[key])
    if existing:
        values.pop("ledger_id", None)  # linked ledger is maintained below for updates
        assignments = ", ".join(f"{column} = ?" for column in values)
        conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", tuple(values.values()) + (existing["id"],))
        item_id = existing["id"]
    else:
        columns = list(values)
        cursor = conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", tuple(values[column] for column in columns))
        item_id = cursor.lastrowid
    if master == "item" and ingredients:
        conn.execute("DELETE FROM item_ingredients WHERE item_id = ?", (item_id,))
        for ingredient in ingredients:
            drug = _lookup(conn, "drug", ingredient)
            conn.execute("INSERT INTO item_ingredients (item_id, drug_id, power) VALUES (?, ?, '')", (item_id, drug["id"]))
    return item_id


def import_rows(master_type: str, validation: dict[str, Any], *, duplicate_mode: str = "skip", confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise ImportErrorDetail("Explicit confirmation is required before import.")
    if duplicate_mode not in {"skip", "update", "cancel"}:
        raise ImportErrorDetail("Duplicate mode must be skip, update, or cancel.")
    if validation.get("invalid_rows"):
        raise ImportErrorDetail("Import has validation errors; correct them before importing.")
    master = _canonical_master(validation["master_type"])
    conn = get_connection()
    result = {"inserted": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}
    try:
        conn.execute("BEGIN")
        for row in validation["rows"]:
            if (row.get("__existing_id") or row.get("__duplicate")) and duplicate_mode == "cancel":
                raise ImportErrorDetail("Duplicate record found; import cancelled.")
            if (row.get("__existing_id") or row.get("__duplicate")) and duplicate_mode == "skip":
                result["skipped"] += 1; continue
            try:
                _write_row(conn, master, row)
                result["updated" if row.get("__existing_id") else "inserted"] += 1
            except Exception as exc:
                result["failed"] += 1
                result["errors"].append(_issue(row["__row__"], "", "", str(exc)))
                raise
        conn.execute("""CREATE TABLE IF NOT EXISTS import_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, master_type TEXT NOT NULL,
            filename TEXT NOT NULL, total_rows INTEGER NOT NULL, inserted INTEGER NOT NULL,
            updated INTEGER NOT NULL, skipped INTEGER NOT NULL, failed INTEGER NOT NULL)""")
        conn.execute("INSERT INTO import_history VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)", (
            datetime.now(timezone.utc).isoformat(), master, validation.get("filename", ""),
            validation.get("total_rows", 0), result["inserted"], result["updated"], result["skipped"], result["failed"]))
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_import_template(master_type: str, fmt: str = "csv") -> bytes:
    master = _canonical_master(master_type)
    headers = list(FIELD_DEFINITIONS[master])
    if fmt.casefold() == "csv":
        return ("\ufeff" + ",".join(headers) + "\n").encode("utf-8")
    if fmt.casefold() == "xlsx":
        if openpyxl is None:
            raise ImportErrorDetail("XLSX templates require the installed openpyxl package.")
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = DISPLAY_NAMES[master]
        sheet.append(headers)
        output = io.BytesIO(); workbook.save(output); workbook.close()
        return output.getvalue()
    raise ImportErrorDetail("Template format must be csv or xlsx.")


def generate_import_report(result: dict[str, Any]) -> str:
    return (f"Inserted: {result.get('inserted', 0)}; Updated: {result.get('updated', 0)}; "
            f"Skipped: {result.get('skipped', 0)}; Failed: {result.get('failed', 0)}")


def get_import_history(limit: int = 20) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS import_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, master_type TEXT NOT NULL,
            filename TEXT NOT NULL, total_rows INTEGER NOT NULL, inserted INTEGER NOT NULL,
            updated INTEGER NOT NULL, skipped INTEGER NOT NULL, failed INTEGER NOT NULL)""")
        conn.commit()
        return [dict(row) for row in conn.execute("SELECT * FROM import_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    finally:
        conn.close()
