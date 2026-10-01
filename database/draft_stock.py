"""Pure calculations for Counter Sale's unsaved, in-memory stock draft.

Nothing in this module persists stock.  It deliberately models only the
quantity shown and validated while an operator is building a bill.
"""

from __future__ import annotations


def reserved_quantity(draft_quantity: float, original_edit_quantity: float = 0.0) -> float:
    """Return the quantity an unsaved draft reserves from stored stock.

    Editing a completed sale is special: the original sale's quantity will be
    restored by the established edit transaction, so it is an allowance and
    must not make the sale unavailable to itself.
    """
    return max(0.0, float(draft_quantity or 0.0) - float(original_edit_quantity or 0.0))


def available_quantity(stored_quantity: float, draft_quantity: float,
                       original_edit_quantity: float = 0.0) -> float:
    """Return display/validation availability without changing stored stock."""
    return max(0.0, float(stored_quantity or 0.0) -
               reserved_quantity(draft_quantity, original_edit_quantity))
