"""Add device_info column to devices table."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from license_server.app import create_app
from license_server.settings import Settings

def migrate():
    """Add device_info column to devices table if it doesn't exist."""
    settings = Settings.from_env()
    app = create_app(settings)
    engine = app.state.engine

    with engine.connect() as conn:
        # Check if column exists
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'devices' AND column_name = 'device_info'
        """))
        if result.fetchone():
            print("device_info column already exists")
        else:
            # Add the column
            conn.execute(text("ALTER TABLE devices ADD COLUMN device_info JSONB"))
            conn.commit()
            print("Added device_info column to devices table")

        # Also check ip_address column
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'devices' AND column_name = 'ip_address'
        """))
        if not result.fetchone():
            conn.execute(text("ALTER TABLE devices ADD COLUMN ip_address VARCHAR(45)"))
            conn.commit()
            print("Added ip_address column to devices table")
        else:
            print("ip_address column already exists")

if __name__ == "__main__":
    migrate()