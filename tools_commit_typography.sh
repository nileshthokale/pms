#!/usr/bin/env bash
# Stage and commit ONLY the files changed by the typography pass.
#
# Deliberately does NOT use `git add -A`: the working tree also contains
# unrelated work in progress (database/backup_restore.py,
# database/pharmacy_a6_receipt.py, screens/backup_restore.py,
# test_a6_pharmacy_printing.py, test_sales_bill_print_format.py,
# test_sales_bill_renderer.py, docs/*, test_balance_sheet_out.txt) that must
# stay uncommitted.
#
# Run from anywhere:
#     bash tools_commit_typography.sh
set -euo pipefail

cd "$(dirname "$0")"

if [ -n "$(git diff --cached --name-only)" ]; then
    echo "error: the index already has staged changes; commit or reset them first:" >&2
    git diff --cached --name-only >&2
    exit 1
fi

FILES=(
    # ── shared typography contract ────────────────────────────────────
    ui/theme.py
    ui/components.py
    ui/navigation_bar.py

    # ── Counter Sale (the screen in the reference screenshot) ─────────
    screens/counter_sale.py

    # ── app-wide sweep: table data 11 -> 13 px ────────────────────────
    screens/account_group_master.py
    screens/account_ledger.py
    screens/account_roles.py
    screens/balance_sheet.py
    screens/company_master.py
    screens/credit_note.py
    screens/customer_master.py
    screens/customer_receipt.py
    screens/day_end.py
    screens/debit_note.py
    screens/doctor_master.py
    screens/drug_master.py
    screens/expiry_report.py
    screens/gst_report.py
    screens/hold_bill.py
    screens/item_master.py
    screens/journal_entry.py
    screens/party_wise_report.py
    screens/profit_loss.py
    screens/purchase_invoice.py
    screens/purchase_report.py
    screens/sales_report.py
    screens/stock_master.py
    screens/supplier_master.py
    screens/supplier_payment.py
    screens/trial_balance.py
    screens/unit_master.py

    # ── tests ─────────────────────────────────────────────────────────
    test_counter_sale_entry_row.py
    test_counter_sale_ui_readability.py
    test_ui_readability_polish.py
    test_ui_typography.py

    # ── tooling introduced by this pass ───────────────────────────────
    tools_screenshot_crop.py
    tools_typography_sweep.py
    tools_visual_acceptance.py
)

git add -- "${FILES[@]}"

echo "--- staged ---"
git diff --cached --name-only
echo "--- $(git diff --cached --name-only | wc -l) file(s) ---"

git commit -F - <<'COMMIT_MSG'
Make UI text larger, bolder and black across every screen

Introduce one shared typography scale in ui/theme.py and apply it across
the application, fixing the small/thin/washed-out text of table data,
captions and totals. The existing spacing and layout geometry is
deliberately left alone: row heights, column widths, panel widths, the
entry bar and the footer keep their current sizes.

- Light palette text is now true black (#000000) for primary text,
  headers and selected rows. Backgrounds, borders, the classic blue
  accent and the red Delete edge are unchanged.
- New TYPE_* scale in px: page title 18, section headers 13, table
  headers 12 bold, table data 13, form labels 12, inputs 13 (12 inside
  the fixed 24 px compact boxes), values 13, NET AMT 14, buttons 12.
- ui/components.py: every size moved from pt to px and raised. Sizes are
  now consistent, because a stylesheet 10pt rendered at ~13.3 px while an
  adjacent 11px rendered at 11 px.
- style_data_table() and polish_page() now set the real QFont alongside
  the stylesheet. Qt honours a stylesheet font-size over setFont(), so
  the two must agree; unstyled tables get the readable floor centrally.
- Counter Sale: table data 11 -> 13 px, table headers 11 -> 12 px bold,
  entry/footer/metadata captions 10 -> 11 px bold black (were grey),
  inputs 11 -> 13 px, totals 12 -> 13 px bold, NET AMT 13 -> 14 px bold.
  _ENTRY_LABEL_MAX_WIDTH 22 -> 30 so the bolder captions cannot clip.
- App-wide sweep: table data 11 -> 13 px, grey _LABEL_DIM field captions
  -> black bold 12 px, _HEADER_LABEL 11 -> 12 px, danger buttons
  11 -> 12 px, bare table headers 9pt -> 12 px. No pt sizes remain in
  screens/ or ui/.
- Tests: the readability tests now assert the larger sizes, bold weight,
  black colour and the real rendered QFont. New test_ui_typography.py
  guards the type scale and adds a source audit so a screen cannot
  reintroduce an undersized table or a grey caption.

Co-Authored-By: Claude Code <noreply@anthropic.com>
COMMIT_MSG

echo "--- committed ---"
git log --oneline -1
echo
echo "Verify with:  git show --stat HEAD"
echo "If the suite fails:  git reset --soft HEAD~1   (unstages, keeps the files)"
