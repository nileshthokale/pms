REPORT_LEDGER_SUBMENU = [
    "Supplier Ledger",
    "Customer Ledger",
    "Itemwise Ledger",
]

REPORT_SALES_SUBMENU = [
    "Daily Billwise Sales",
    "Daily Itemwise Sales",
    "Companywise Sales",
    "Itemwise Sales",
    "Daily Profit Calculation",
    "Daily Profit Itemwise",
]

REPORT_PURCHASE_SUBMENU = [
    "Companywise Itemwise Purchase",
    "Companywise Supplierwise Purchase",
    "---",
    "Supplierwise Itemwise Purchase (Invoice)",
    "Supplierwise Itemwise Purchase (Challan)",
    "---",
    "Itemwise Purchase",
    "Itemwise Batchwise Purchase",
]


REPORT_STOCK_SUBMENU = [
    "Items (All) Stock",
    "Companywise Item Stock",
    "Expired Item List",
    "Item List",
]


REPORT_DOCTOR_SUBMENU = [
    "Doctorwise Item Sale",
    "Doctorwise Item Sale Details",
]


class SubmenuDict(dict):
    """Submenu dict that compares equal to its string title for backward compatibility."""

    def __eq__(self, other):
        if isinstance(other, str) and other in self:
            return True
        return super().__eq__(other)


MENUS = {
    "Sales": [
        "New Bill",
        "Hold Bill",
        "Return Bill",
        "Sales History",
        "Day End",
    ],
    "Purchase": [
        "New Purchase",
        "Purchase Return",
        "Purchase History",
        "Supplier Payment",
    ],
    "Account": [
        "Debit Note (Return to Supplier)",
        "Credit Note (Return from Customer)",
        "Supplier Payment Voucher",
        "Customer Receipt Voucher",
        "Cash Book",
        "Bank Book",
        "Ledger",
        "Journal Entry",
        "Account Roles",
        "Trial Balance",
        "Profit & Loss",
        "Balance Sheet",
    ],
    "Reports": [
        SubmenuDict({
            "Sales Report": REPORT_SALES_SUBMENU,
        }),
        "Duplicate Sales Bill",
        SubmenuDict({
            "Purchase Report": REPORT_PURCHASE_SUBMENU,
        }),
        SubmenuDict({
            "Stock Report": REPORT_STOCK_SUBMENU,
        }),
        SubmenuDict({
            "Doctor's Reports": REPORT_DOCTOR_SUBMENU,
        }),
        "Expiry Report",
        "Party Wise Report",
        "GST Report",
        {
            "Ledger": REPORT_LEDGER_SUBMENU,
        },
    ],
    "Master": [
        "Item Master",
        "Company Master",
        "Unit Master",
        "Drug Master",
        "Supplier Master",
        "Customer Master",
        "Doctor Master",
        "Account Group",
        "Import Data",
        "Financial Year",
        "Category Master",
        "User Master",
        "Backup & Restore",
    ],
}
