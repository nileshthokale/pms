"""GST tax structures and legacy tax-code provenance for Item Master.

The Item Master "Tax Structure" control is a fixed dropdown offering exactly
five GST options.  The *display* text is descriptive, but every consumer reads
the *internal* value: the bare GST rate as a string ("0", "5", "12", "18",
"28"), which is also what is stored in ``items.tax_structure``.

Storage
-------
``items.tax_structure`` is a plain TEXT column with no lookup table and no
CHECK constraint, so nothing here needs a schema change.  Items imported from
the old Pharma-WINNER system originally held **legacy numeric tax codes**
(``'1'`` .. ``'15'``, from ``itemmst.TaxID``) rather than GST rates — see
``docs/legacy_data_migration.md`` and ``docs/item_master_tax_mapping_phase1.md``.
No tax master table exists in the source dump, so the true historical rate for
those codes was never recoverable.

The owner decision is **flag all, convert none**: a legacy code is never
guessed at and never rewritten, and the user is shown the explicit
"Legacy Tax Code N — Mapping Required" flag instead of a bare number or an
invented GST name.

Provenance
----------
``items.legacy_tax_id`` records where the stored value came from:

* ``NULL`` — a genuine new-system GST selection.
* non-``NULL`` — the old Pharma-WINNER ``TaxID`` that was preserved for audit.

A later owner-approved pass (``tools/apply_gst_only_tax_mapping.py``) rewrote
``tax_structure`` to GST rates for the migrated items using GST-era evidence,
while leaving ``legacy_tax_id`` byte-identical.  So the two fields can now
disagree, and the *stored value* is what the user is shown: a value that is a
genuine GST rate displays as GST, an unmapped legacy code displays the flag,
and EMPTY (a VAT-only item) displays blank.

Ambiguity
---------
The legacy code ``'12'`` is numerically equal to GST 12%.  Two different
questions have two different answers, deliberately:

* :func:`display_for` — a bare stored value with **no provenance information**
  at all.  A known legacy code takes precedence over the numeric coincidence,
  so ``'12'`` is flagged.  This is the conservative reading.
* :func:`resolve_tax_display` — provenance is available.  A value that is a
  genuine GST rate is named as GST, so a migrated item the owner remapped to
  GST 12% shows ``GST @ 12% (CGST-6% & SGST-6%)``.  Called with no provenance
  argument it defers to :func:`display_for`, so an unqualified ``'12'`` still
  flags rather than colliding.

Nothing here ever rewrites a stored value.
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

# The em-dash U+2014 is part of the user-facing label.  This file is UTF-8
# (the Python 3 default), and the tests assert the same character as —.
_FLAG = "Legacy Tax Code {code} — Mapping Required"

# Sentinel meaning "the caller supplied no provenance information", which is
# strictly weaker than an explicit ``None`` (= provenance recorded as NULL, so
# the value is known to be a genuine new-system GST selection).  The
# distinction is what lets an unqualified '12' stay flagged while a '12' whose
# provenance is NULL is named as GST.
_PROVENANCE_UNKNOWN = object()

# OLD Pharma-WINNER TaxID -> proposed GST conversion.
#
# ``new`` is always ``None``: per the owner decision the mapping is *proposed*
# and unverified, and no GST rate may be assigned to a legacy code without
# owner verification.  ``status`` is AMBIGUOUS or UNKNOWN for every code; a
# future VERIFIED entry carries the verified GST value in ``new`` and starts
# displaying as that GST rate with no other code change.
#
# Counts and the historical ``TaxPer`` evidence behind each status are the
# source ``itemmst.TaxID`` distribution and the purchase-side ``TaxPer``
# history, tabulated in ``docs/item_master_tax_mapping_phase1.md``.  The
# statuses and reasons below are that table, and the 10 keys are the only
# TaxID values present in the imported data.
LEGACY_TAX_ID_MAPPING: dict[str, dict[str, object]] = {
    "1": {
        "new": None,
        "status": "AMBIGUOUS",
        "reason": "5 items; historical TaxPer 0 throughout, no tax master in dump",
    },
    "2": {
        "new": None,
        "status": "AMBIGUOUS",
        "reason": "43 items; historical TaxPer 0 for 25, remainder absent",
    },
    "4": {
        "new": None,
        "status": "UNKNOWN",
        "reason": "1 item; single historical TaxPer 12.5, a VAT-era rate",
    },
    "6": {
        "new": None,
        "status": "AMBIGUOUS",
        "reason": "305 items; TaxPer split 5/5.5/6 with no 12/18/28",
    },
    "7": {
        "new": None,
        "status": "AMBIGUOUS",
        "reason": "18 items; bimodal TaxPer 12.5/13.5 against the 5 family",
    },
    "11": {
        "new": None,
        "status": "AMBIGUOUS",
        "reason": "220 items; TaxPer 12 in only a 63% plurality, 37% other",
    },
    "12": {
        "new": None,
        "status": "AMBIGUOUS",
        "reason": (
            "323 items; TaxPer 12 in only a 62% plurality, 35% at 5/5.5/6. "
            "Numerically equals GST 12% but the old meaning is unverified"
        ),
    },
    "13": {
        "new": None,
        "status": "AMBIGUOUS",
        "reason": "24 items; TaxPer 18 in 83% of rows plus VAT residue",
    },
    "14": {
        "new": None,
        "status": "AMBIGUOUS",
        "reason": "2 items; TaxPer split 12.5/13.5/28",
    },
    "15": {
        "new": None,
        "status": "UNKNOWN",
        "reason": "1 item; single historical TaxPer row of 0",
    },
}

# The legacy codes present in the imported data, in ascending order.
LEGACY_TAX_IDS: tuple[str, ...] = tuple(LEGACY_TAX_ID_MAPPING)


def _text(value: object) -> str:
    """The stored value as a trimmed string; empty for ``None``."""
    return "" if value is None else str(value).strip()


def display_for(value: object) -> str:
    """The label for a stored value when **no provenance is known**.

    A known legacy code takes precedence over a numeric GST coincidence, so
    ``'12'`` is flagged rather than shown as GST.  An unrecognised value is
    returned unchanged, so no historical code is silently relabelled as GST.
    """
    text = _text(value)
    if not text:
        return ""
    entry = LEGACY_TAX_ID_MAPPING.get(text)
    if entry is not None:
        if entry["status"] == "VERIFIED":
            verified = _text(entry.get("new"))
            if is_gst_rate(verified):
                return _DISPLAY_BY_VALUE[verified]
        return legacy_flag_label(text)
    return _DISPLAY_BY_VALUE.get(text, text)


def legacy_flag_label(value: object) -> str:
    """The explicit flag shown for a legacy tax code.

    Never a bare number and never a guessed GST name: the owner decision is to
    flag every unmapped code so the user must resolve the mapping themselves.
    """
    text = _text(value)
    return _FLAG.format(code=text) if text else ""


def legacy_display(value: object) -> str:
    """Label for a stored value that is not one of the five GST options.

    The dialog uses this for the extra entry it appends for an imported item.
    Same text as :func:`legacy_flag_label` — the two names exist because the
    dialog reads a "display" while the grid reads a "flag".
    """
    return legacy_flag_label(value)


def resolve_tax_display(
    value: object,
    legacy_tax_id: object = _PROVENANCE_UNKNOWN,
    mapping: dict[str, dict[str, object]] | None = None,
) -> str:
    """Grid label for a stored tax value, using provenance when it is supplied.

    ``legacy_tax_id`` is the item's recorded provenance:

    * omitted — provenance unknown, so defer to :func:`display_for` and flag a
      known legacy code even when it numerically equals a GST rate;
    * ``None`` — provenance recorded as NULL, so a GST rate is a genuine
      new-system selection and is named as GST;
    * non-``NULL`` — a preserved legacy code; consult ``mapping`` for a
      verified conversion, otherwise flag it.

    ``mapping`` overrides :data:`LEGACY_TAX_ID_MAPPING` (used by tests and by
    a future verified mapping without touching the shipped table).

    EMPTY always displays blank: a VAT-only imported item has no GST label.
    """
    text = _text(value)
    if not text:
        return ""
    if legacy_tax_id is _PROVENANCE_UNKNOWN and mapping is None:
        return display_for(text)
    if is_gst_rate(text):
        # A genuine GST value: either a new selection (NULL provenance) or a
        # migrated item the owner remapped to GST.  Named as GST in both cases.
        return _DISPLAY_BY_VALUE[text]
    table = LEGACY_TAX_ID_MAPPING if mapping is None else mapping
    entry = table.get(text)
    if entry is not None and entry.get("status") == "VERIFIED":
        verified = _text(entry.get("new"))
        if is_gst_rate(verified):
            return _DISPLAY_BY_VALUE[verified]
    return legacy_flag_label(text)


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
