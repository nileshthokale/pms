"""GST tax structures for Item Master.

The Item Master "Tax Structure" control is a fixed dropdown offering exactly
five GST options.  The *display* text is descriptive, but every consumer reads
the *internal* value: the bare GST rate as a string ("0", "5", "12", "18",
"28"), which is also what is stored in ``items.tax_structure``.

Storage
-------
``items.tax_structure`` is a plain TEXT column with no lookup table and no
CHECK constraint, so nothing here needs a schema change.  Imported items
hold **legacy numeric tax codes** from the old system (``'1'`` .. ``'15'``)
rather than GST rates — see ``docs/legacy_data_migration.md``.  Those codes
are preserved verbatim and never rewritten; ``is_gst_rate()`` is the only
thing that distinguishes them.

Important: the legacy code ``'12'`` is numerically equal to GST 12%, so a
stored value of ``'12'`` is genuinely ambiguous.  It is reported as a GST
rate here, and the Item Master keeps it intact on save, so nothing is lost
either way.  Note the caveat: an imported item whose legacy code is ``'12'``
will therefore *display* as "GST @ 12%" even though its real historical
tax master row was never available (``docs/legacy_data_migration.md``).
The stored value round-trips unchanged, so no data is rewritten — only the
label is an interpretation, and it is the same interpretation the Purchase
screen already made for such items.
"""

from __future__ import annotations

# (display text, internal value).  Order is the dropdown order.
GST_TAX_STRUCTURES: tuple[tuple[str, str], ...] = (
    ("GST @ 5% (CGST-2.5% & SGST-2.5%)", "5"),
    ("GST @ 12% (CGST-6% & SGST-6%)", "12"),
    ("GST @ 18% (CGST-9% & SGST-9%)", "18"),
    ("GST @ 28% (CGST-14% & SGST-14%)", "28"),
    ("ZERO GST", "0"),
)

# The only values a *new* item may be saved with.
VALID_TAX_VALUES: tuple[str, ...] = tuple(v for _, v in GST_TAX_STRUCTURES)

# Default for a new item.  Deliberately ZERO GST: no non-zero rate is ever
# pre-selected, so creating an item can never silently imply a tax liability.
DEFAULT_TAX_VALUE = "0"

_DISPLAY_BY_VALUE = {value: text for text, value in GST_TAX_STRUCTURES}


def display_for(value: object) -> str:
    """Return the dropdown label for an internal value.

    An unrecognised (legacy) value is returned unchanged, so historical codes
    survive display without being rewritten.
    """
    text = "" if value is None else str(value).strip()
    return _DISPLAY_BY_VALUE.get(text, text)


def is_gst_rate(value: object) -> bool:
    """True when the stored value is one of the five supported GST rates."""
    if value is None:
        return False
    return str(value).strip() in VALID_TAX_VALUES


def rate_percent(value: object) -> float | None:
    """The GST percentage for an internal value, or None if unsupported.

    ``None`` means "not a supported GST rate" — callers must treat that as
    *unknown*, never as zero.  Legacy codes deliberately return None so no
    tax amount is ever invented for an imported item.
    """
    if not is_gst_rate(value):
        return None
    return float(str(value).strip())


def legacy_display(value: object) -> str:
    """Label for a stored value that is not one of the five GST options."""
    text = "" if value is None else str(value).strip()
    return f"{text} (legacy tax code)" if text else ""