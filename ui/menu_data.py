REPORT_LEDGER_SUBMENU = [
    "Supplier Ledger",
    "Customer Ledger",
    "Itemwise Ledger",
]

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
        "Sales Report",
        "Purchase Report",
        "Stock Report",
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
