"""Financial-year view plumbing shared by the report screens.

The navigation bar's FY button reports the chosen year to every page that
implements ``set_history_financial_year(year)`` — see
:meth:`ui.main_window.PharmacyMainWindow._on_financial_year_view`.  This
module holds the small shared pieces those pages need, so that every report
reacts to a financial-year change in exactly the same way and none of them
can accidentally fall back to showing every year at once.

Two distinct ideas are kept apart on purpose:

* the **active** financial year — the one new transactions are written to,
  changed from Master > Financial Year;
* the **viewed** financial year — a display-only filter chosen from the
  navigation bar.  Viewing never activates a year and never writes anything.
"""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QMessageBox

from database import financial_year


def view_year_bounds(year: dict | None) -> tuple[str, str]:
    """Return the ``(start, end)`` ISO dates for a financial-year row.

    Falls back to the active financial year when *year* is missing or
    malformed, so a report is never left showing an unbounded range — an
    unbounded range is what mixes several years together in one list.
    """
    if year:
        start = str(year.get("start_date") or "")
        end = str(year.get("end_date") or "")
        if start and end:
            return start, end
    return financial_year.active_date_range()


def set_date_edit(edit, iso_date: str) -> bool:
    """Move a ``QDateEdit`` to an ISO date without triggering its signals.

    Returns ``False`` when the date cannot be parsed, leaving the widget
    untouched rather than resetting it to today.
    """
    parsed = QDate.fromString(str(iso_date), "yyyy-MM-dd")
    if not parsed.isValid():
        return False
    edit.blockSignals(True)
    edit.setDate(parsed)
    edit.blockSignals(False)
    return True


def apply_range(start_edit, end_edit, year: dict | None) -> tuple[str, str]:
    """Point a From/To date pair at *year* (or the active year) and return it."""
    start, end = view_year_bounds(year)
    set_date_edit(start_edit, start)
    set_date_edit(end_edit, end)
    return start, end


def confirm_transaction_date(parent, value: str, *, action: str = "record") -> bool:
    """Decide whether a transaction dated *value* may be saved.

    A date inside the active financial year passes silently.  A date that
    belongs to a different financial year asks for explicit confirmation, so
    historical records can still be entered deliberately but are never
    backdated by accident.  A date outside every known financial year is
    refused, because there would be no year to report it under.
    """
    try:
        target = financial_year.get_financial_year_for_date(value)
        active = financial_year.get_active_financial_year()
    except financial_year.FinancialYearError as exc:
        QMessageBox.warning(parent, "Financial Year", str(exc))
        return False

    if target is None:
        QMessageBox.warning(
            parent,
            "Financial Year",
            f"{value} does not fall inside any financial year.\n\n"
            "Create that financial year first "
            "(Master > Financial Year), then save again.",
        )
        return False

    if active is None or target["id"] == active["id"]:
        return True

    answer = QMessageBox.question(
        parent,
        "Historical Financial Year",
        f"{value} falls in financial year {target['name']}, which is not the "
        f"active year ({active['name']}).\n\n"
        f"Save this {action} in {target['name']}?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    return answer == QMessageBox.Yes
