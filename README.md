# Pharmacy Management System

A comprehensive desktop application for managing pharmacy operations, built with Python and PySide6 (Qt6).

## Features

### Core Modules
- **Inventory Management**: Drug master, stock tracking, expiry reports, category/unit management
- **Sales & Billing**: Counter sales, sales invoices, hold bills, sales reports
- **Purchase Management**: Purchase invoices, supplier management, purchase reports
- **Accounting**: 
  - Ledger management, account groups, account roles
  - Journal entries, debit/credit notes
  - Cash book, bank book, day-end processing
  - Trial balance, profit & loss, balance sheet
  - Party-wise reports, GST reports
- **Financial Year Management**: Multi-year support with opening/closing balances
- **User Management**: Authentication, user roles and permissions
- **Backup & Restore**: Database backup and restore functionality
- **Document Printing**: A6 pharmacy receipts, invoices, reports

### Technical Stack
- **Language**: Python 3.x
- **GUI Framework**: PySide6 (Qt6)
- **Database**: SQLite (with WAL mode)
- **Architecture**: Modular design with separation of concerns (database layer, UI screens, business logic)

## Project Structure

```
Pharmacy Management System/
├── main.py                    # Application entry point
├── run_tests.py               # Test runner
├── database/                  # Data access layer
│   ├── connection.py          # Database connection & initialization
│   ├── auth.py                # Authentication & user management
│   ├── *_dao.py               # Data Access Objects for each entity
│   └── *_report_dao.py        # Reporting queries
├── screens/                   # UI screens/modules
│   ├── login.py               # Login dialog
│   ├── *_master.py            # Master data entry screens
│   ├── *_report.py            # Report viewing screens
│   └── *.py                   # Transaction screens (sales, purchase, etc.)
├── ui/                        # Core UI components
│   ├── main_window.py         # Main application window
│   ├── navigation_bar.py      # Navigation sidebar
│   ├── menu_data.py           # Menu structure
│   ├── theme.py               # Application theming
│   └── components.py          # Reusable UI components
└── test_*.py                  # Unit & integration tests
```

## Requirements

- Python 3.8+
- PySide6

Install dependencies:
```bash
pip install PySide6
```

## Running the Application

```bash
python main.py
```

## Running Tests

```bash
python run_tests.py
```

Or run specific test files:
```bash
python test_sales_report.py
python test_purchase_posting.py
# etc.
```

## Database

The application uses SQLite databases. On first run, the database schema is automatically created. Backup files (`.db`, `.db-wal`, `.db-shm`) are created automatically.

## Key Features Detail

### Inventory
- Drug master with batch tracking, expiry dates, MRP, sale/purchase rates
- Stock management with real-time updates
- Expiry alerts and reports
- Category, unit, and tax structure management

### Sales
- Counter sales with keyboard-friendly entry
- Sales bill review and modification
- Hold bills for pending transactions
- Customer management and receipts

### Purchase
- Purchase invoice entry with GST support
- Supplier management and payments
- Debit/credit notes for returns

### Accounting
- Double-entry bookkeeping
- Financial year management
- Comprehensive financial reports (Trial Balance, P&L, Balance Sheet)
- GST compliance reports (GSTR-1, GSTR-3B)
- Cash/Bank book with reconciliation

### User Management
- Role-based access control
- User activation/deactivation
- Audit trail for critical operations

## License

Proprietary - Internal Use Only

## Configuration

### Environment Variables
Create a `.env` file in the project root for configuration:
```env
DB_PATH=pharmacy.db
BACKUP_DIR=backups
LOG_LEVEL=INFO
APP_THEME=light
```

### Database Configuration
- Default database: `pharmacy.db` (SQLite with WAL mode enabled)
- Backup directory: `backups/` (auto-created)
- WAL files: `pharmacy.db-wal`, `pharmacy.db-shm`

### Theme Customization
Edit `ui/theme.py` to customize colors, fonts, and styling. Supports light/dark modes.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+N` | New transaction (context-aware) |
| `Ctrl+S` | Save current form |
| `Ctrl+P` | Print current document |
| `Ctrl+F` | Search/focus search field |
| `Escape` | Close dialog/cancel |
| `Enter` | Submit form/next field |
| `Tab` | Next field |
| `Shift+Tab` | Previous field |
| `F1` | Help/About |
| `Ctrl+Q` | Quit application |

## Building & Distribution

### Create Executable (PyInstaller)
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "PharmacyMS" --icon=assets/icon.ico main.py
```

### Create Installer (Inno Setup)
Use the provided `installer.iss` script for Windows installer creation.

## Architecture Overview

```
┌─────────────────────────────────────┐
│           Main Window               │
│  (Navigation + Screen Container)    │
└──────────────┬──────────────────────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
┌───────┐ ┌─────────┐ ┌──────────┐
│ Screens │ │ UI Core │ │ Database │
│ (Business│ │ (Theme, │ │ Layer    │
│  Logic)  │ │  Nav)   │ │ (DAOs)   │
└───────┘ └─────────┘ └──────────┘
    │                    │
    └──────────┬─────────┘
               ▼
        ┌────────────┐
        │  SQLite DB │
        │  (WAL mode)│
        └────────────┘
```

### Design Patterns Used
- **DAO Pattern**: Data Access Objects for each entity (`*_dao.py`)
- **MVC-lite**: Screens handle UI + business logic, DAOs handle data
- **Dependency Injection**: Database connection passed to DAOs
- **Observer Pattern**: Navigation bar updates on screen changes
- **Factory Pattern**: Screen instantiation via menu data

## Troubleshooting

### Common Issues

**Database Locked Error**
```bash
# Remove WAL/SHM files if stuck
del pharmacy.db-wal pharmacy.db-shm
```

**Import Errors**
```bash
# Reinstall dependencies
pip install --upgrade PySide6
```

**Theme Not Applying**
- Check `ui/theme.py` for syntax errors
- Restart application after theme changes

**Print Issues**
- Ensure default printer is set in Windows
- Check paper size (A6 for receipts)

### Logs
Application logs to console by default. Set `LOG_LEVEL=DEBUG` in `.env` for verbose output.

## Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/new-feature`
3. Follow existing code style (PEP 8, type hints)
4. Add tests for new functionality
5. Run test suite: `python run_tests.py`
6. Submit pull request

### Code Style Guidelines
- Use type hints for all functions
- Follow PEP 8 naming conventions
- Document public methods with docstrings
- Keep screens focused on single responsibility
- DAOs should only contain database queries

## Changelog

### v2.0.0 (Current)
- Migrated from PyQt5 to PySide6 (Qt6)
- Added Financial Year Management
- Implemented GST Reports (GSTR-1, GSTR-3B)
- Enhanced Accounting Module (Trial Balance, P&L, Balance Sheet)
- Added Backup/Restore functionality
- Improved UI theming system

### v1.x
- Initial release with core pharmacy modules
- Inventory, Sales, Purchase, Basic Accounting
- SQLite database with basic schema

## Support

For issues or feature requests, contact the development team or create an issue in the internal tracker.

## Screenshots

*Add screenshots here showing:*
- Login Screen
- Main Dashboard
- Inventory Management
- Sales Counter
- Purchase Entry
- Accounting Reports
- GST Reports