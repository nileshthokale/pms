"""Add ip_address column to devices table."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from license_server.app import create_app
from license_server.settings import Settings

def migrate():
    """Add ip_address column to devices table if it doesn't exist."""
    settings = Settings.from_env()
    app = create_app(settings)
    engine = app.state.engine

    with engine.connect() as conn:
        # Check if column exists
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'devices' AND column_name = 'ip_address'
        """))
        if result.fetchone():
            print("ip_address column already exists")
            return

        # Add the column
        conn.execute(text("ALTER TABLE devices ADD COLUMN ip_address VARCHAR(45)"))
        conn.commit()
        print("Added ip_address column to devices table")

if __name__ == "__main__":
    migrate()