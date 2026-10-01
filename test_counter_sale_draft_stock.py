"""Headless regression tests for Counter Sale's live draft stock rules.

These use no production database and no Qt widgets.  UI tests exercise the
same helper through ``screens.counter_sale._SalePanel`` when PySide6 is
available; these tests keep the stock contract enforceable everywhere.
"""

from __future__ import annotations

import unittest

from database.draft_stock import available_quantity, reserved_quantity


class TestCounterSaleDraftStock(unittest.TestCase):
    def test_reservation_never_changes_stored_input(self):
        stored = 6.0
        self.assertEqual(stored, 6.0)
        self.assertEqual(available_quantity(stored, 1), 5.0)
        self.assertEqual(stored, 6.0)


def _case(name: str, stored: float, draft: float, original: float,
          expected_reserved: float, expected_available: float):
    def test(self):
        self.assertEqual(reserved_quantity(draft, original), expected_reserved)
        self.assertEqual(available_quantity(stored, draft, original), expected_available)
    test.__name__ = name
    return test


# 48 independently reported examples: additions, deletion/clear states,
# independent batches (represented by independent calls), and edit allowance.
_CASES = [
    (6, 0, 0, 0, 6), (6, 1, 0, 1, 5), (6, 2, 0, 2, 4),
    (6, 3, 0, 3, 3), (6, 4, 0, 4, 2), (6, 5, 0, 5, 1),
    (6, 6, 0, 6, 0), (6, 7, 0, 7, 0), (10, 1, 0, 1, 9),
    (10, 2, 0, 2, 8), (10, 5, 0, 5, 5), (10, 10, 0, 10, 0),
    (2, 1, 0, 1, 1), (2, 2, 0, 2, 0), (2, 3, 0, 3, 0),
    (0, 0, 0, 0, 0), (0, 1, 0, 1, 0), (1, 0, 0, 0, 1),
    (1, 1, 0, 1, 0), (1, 2, 0, 2, 0), (12, 4, 0, 4, 8),
    (12, 8, 0, 8, 4), (12, 12, 0, 12, 0), (5, 0, 0, 0, 5),
    (5, 3, 0, 3, 2), (5, 5, 0, 5, 0),
    # Edit workflow: original quantity is available to that transaction.
    (4, 2, 2, 0, 4), (4, 3, 2, 1, 3), (4, 4, 2, 2, 2),
    (4, 6, 2, 4, 0), (6, 2, 2, 0, 6), (6, 3, 2, 1, 5),
    (6, 6, 2, 4, 2), (6, 8, 2, 6, 0), (3, 1, 2, 0, 3),
    (3, 2, 2, 0, 3), (3, 3, 2, 1, 2), (3, 5, 2, 3, 0),
    # Delete and clear are simply smaller draft totals.
    (9, 5, 0, 5, 4), (9, 2, 0, 2, 7), (9, 0, 0, 0, 9),
    (7, 4, 0, 4, 3), (7, 1, 0, 1, 6), (7, 0, 0, 0, 7),
    # Fractional stock must remain exact at this layer.
    (6.5, 1.5, 0, 1.5, 5.0), (6.5, 6.5, 0, 6.5, 0),
    (6.5, 7.0, 0, 7.0, 0), (6.5, 2.5, 1.0, 1.5, 5.0),
]

for _index, _values in enumerate(_CASES, 1):
    setattr(TestCounterSaleDraftStock, f"test_{_index:02d}_draft_availability", 
            _case(f"test_{_index:02d}_draft_availability", *_values))


if __name__ == "__main__":
    unittest.main()
