"""Create the existing central licensing schema only; never access pharmacy data."""
import argparse

from sqlalchemy import create_engine

from license_server.models import Base
from license_server.settings import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read-only schema readiness check")
    args = parser.parse_args()
    settings = Settings.from_env()
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 5})
    try:
        if args.check:
            from sqlalchemy import inspect
            actual = set(inspect(engine).get_table_names())
            missing = set(Base.metadata.tables) - actual
            if missing:
                raise SystemExit("Missing licensing tables: " + ", ".join(sorted(missing)))
            print("Existing licensing schema v1 is ready.")
        else:
            # No second declarative Base or conflicting schema; existing tables remain intact.
            Base.metadata.create_all(engine)
            print("Existing licensing schema v1 created/verified without changing existing rows.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
