"""Centralized document and voucher number display formatter.

Provides uniform numeric-only presentation of bill and voucher numbers across all
screens, tables, dialogs, reports, and print/PDF outputs, while preserving full
compound identifiers and database integrity internally.
"""

from __future__ import annotations

import re
from typing import Any, Optional


def format_document_number(value: Any, default: str = "") -> str:
    """Return only the numeric / sequence component of a bill or voucher number for display.

    Standard rules:
    - Compound FY + type + number (e.g. '2026-2027-Credit-0251' -> '0251', preserving leading zeros)
    - Compound FY + number (e.g. '2026-2027-1905' -> '1905', '2017-2018-1' -> '1', '2023-2024-250' -> '250')
    - Legacy fallback with source row & ID (e.g. '2026-2027-Cash-187-S72213' -> '187', underlying voucher number)
    - Collision suffix (e.g. '2026-2027-1905#12345' -> '1905', '2015-2016-1#51' -> '1')
    - Standard prefix + number (e.g. 'PV-0001' -> '0001', 'CN-0001' -> '0001', 'PUR-0042' -> '0042')
    - Bare numbers (e.g. '1905' -> '1905', '0251' -> '0251')
    - Empty or placeholder values ('--', '---', None, '') -> returned safely without error
    - Dates ('2026-05-01') and pure FY names ('2026-2027') are preserved without alteration
    - Non-numeric test identifiers ('CS-KEEP', 'DRAFT') are returned unchanged without inventing a number
    """
    if value is None:
        return default
    text = str(value).strip()
    if not text or text in ("--", "---"):
        return text or default

    # Preserve pure ISO dates and pure financial-year range strings
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text) or re.match(r"^\d{4}-\d{4}$", text):
        return text

    # Strip deterministic collision suffix (e.g. '#12345')
    if "#" in text:
        text = text.split("#", 1)[0].strip()

    # Strip legacy migration fallback suffix '-S<legacy_id>' (e.g. '-S72213')
    # Legacy migration created {fy}-{vh_type}-{vh_no}-S{legacy_id}; removing -S{id}
    # exposes {vh_no} at the tail.
    text = re.sub(r"-[sS]\d+$", "", text)

    # If already pure digits, return as-is
    if text.isdigit():
        return text

    # Extract numeric sequence after last hyphen or slash delimiter
    if "-" in text:
        tail = text.rsplit("-", 1)[-1].strip()
        if tail.isdigit():
            return tail
    elif "/" in text:
        tail = text.rsplit("/", 1)[-1].strip()
        if tail.isdigit():
            return tail

    return text


def format_sales_bill_number(value: Any, patient_name: Any = None, default: str = "") -> str:
    """Return the display sales bill number for a sale.

    When the original stored patient name is empty or whitespace-only, the
    sale was created without a patient and its business Bill No is displayed
    as blank.  ``patient_name=None`` means the caller did not supply the
    name, so the number is formatted normally.  A genuinely blank stored
    number is always returned blank.
    """
    if patient_name is not None and not str(patient_name).strip():
        return default
    return format_document_number(value, default=default)


def match_document_query(stored_value: Any, query: str) -> bool:
    """Return True if stored_value matches query, comparing both raw and formatted forms."""
    if not query:
        return True
    q = str(query).strip().casefold()
    if not q:
        return True
    stored_str = str(stored_value or "").strip().casefold()
    if q == stored_str:
        return True
    # If the user typed a compound or prefixed query (containing hyphens or letters),
    # match against stored_str
    if ("-" in q or any(c.isalpha() for c in q)) and q in stored_str:
        return True

    formatted = format_document_number(stored_value).casefold()
    if q in formatted:
        return True
    # Leading-zero tolerance for numeric queries e.g. query '251' matches '0251'
    if q.isdigit() and formatted.isdigit():
        if int(q) == int(formatted):
            return True
        if q.lstrip('0') and formatted.lstrip('0') and q.lstrip('0') == formatted.lstrip('0'):
            return True
    return False


def format_purchase_voucher_number(
    value: Any,
    default: str = "",
    purchase_type: Optional[str] = None,
) -> str:
    """Return only the original voucher number of a purchase voucher for display,
    removing financial year and voucher-type prefix formatting, while stripping
    unnecessary leading zeros for pure numeric vouchers to match Pharma-WINNER.

    Examples:
    - '2026-2027-Credit-0251' -> '251'
    - '2026-2027-Credit-79' -> '79'
    - '2025-2026-Cash-80' -> '80'
    - '2024-2025-Credit-368' -> '368'
    - '2026-2027-Challan-1' -> '1'
    - '2026-2027-Credit-1905#12345' -> '1905'
    - '2026-2027-Cash-187-S72213' -> '187'
    - 'PV-0001' -> '1'
    - 'PV-101' -> '101'
    - '2026-2027-1905' -> '1905'
    - '2026-2027-Credit-V001' -> 'V001'
    - 'V001' -> 'V001'
    - '0252' -> '252'
    - '252' -> '252'
    """
    if value is None:
        return default
    text = str(value).strip()
    if not text or text in ("--", "---"):
        return text or default

    # 1. Strip collision suffix (e.g. '#12345')
    if "#" in text:
        text = text.split("#", 1)[0].strip()

    # 2. Strip legacy migration row ID suffix (e.g. '-S72213')
    text = re.sub(r"-[sS]\d+$", "", text)

    # 3. Strip financial year prefix (e.g. '2026-2027-', '2024-2025-', '2015-2016-')
    text = re.sub(r"^(?:FY)?\d{4}-\d{2,4}-", "", text, flags=re.IGNORECASE)

    # 4. Strip confirmed voucher-type prefix
    pt = (purchase_type or "").strip()
    if pt and text.lower().startswith(f"{pt.lower()}-"):
        text = text[len(pt) + 1:].strip()
    else:
        text = re.sub(
            r"^(?:Credit|Cash|Challan|Debit|Credit\s*Note|Debit\s*Note|Credit\s*Card|PV|PUR|P)-",
            "",
            text,
            flags=re.IGNORECASE,
        )

    # 5. Pure digits: strip leading zeros to match Pharma-WINNER integer VhNo
    if text.isdigit():
        return str(int(text))

    return text


def format_time_12hr(value: Any, default: str = "") -> str:
    """Convert any time string (24-hour '19:56', '19:56:00', or 12-hour '07:56 PM', etc.)
    consistently to 12-hour format with AM/PM without leading zero on hour,
    e.g. '7:56 PM', '10:18 AM', '12:44 PM'.
    """
    if value is None:
        return default
    text = str(value).strip()
    if not text or text in ("--", "---"):
        return text or default
    upper = text.upper()
    from datetime import datetime
    for fmt in ("%I:%M:%S %p", "%I:%M %p", "%I:%M:%S%p", "%I:%M%p",
                "%H:%M:%S", "%H:%M"):
        try:
            dt = datetime.strptime(upper, fmt)
            hour = dt.hour % 12
            if hour == 0:
                hour = 12
            am_pm = "AM" if dt.hour < 12 else "PM"
            return f"{hour}:{dt.minute:02d} {am_pm}"
        except ValueError:
            continue
    return text


__all__ = [
    "format_document_number",
    "format_purchase_voucher_number",
    "format_sales_bill_number",
    "format_time_12hr",
    "match_document_query",
]
