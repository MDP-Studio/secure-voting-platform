import os
import sys
import shutil
from datetime import datetime
from dotenv import load_dotenv

from app import create_app
from app.init_db import init_database

# Load .env first so MAIL_* and other settings are available
load_dotenv()

DB_DIR = "instance"
DB_PATH = os.path.join(DB_DIR, "app.db")


def ensure_instance_dir():
    """Ensure the instance/ folder exists (used by SQLite DB)."""
    os.makedirs(DB_DIR, exist_ok=True)


def backup_db(db_path: str) -> str | None:
    """
    Create a backup of the existing SQLite database before deletion.
    Returns the backup file path if successful, or None.
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(DB_DIR, f"app_{timestamp}.db")
        shutil.copy2(db_path, backup_path)
        return backup_path
    except Exception as e:
        print(f"⚠️ Failed to backup database: {e}")
        return None


def ask_should_reset() -> bool:
    """
    Ask the user whether to reset the database.
    Supports command-line arguments:
      --reset     → reset DB without asking
      --no-input  → keep DB without asking
    
    In non-interactive environments (CI/CD), defaults to keeping existing DB.
    """
    argv = set(arg.lower() for arg in sys.argv[1:])
    if "--reset" in argv:
        return True
    if "--no-input" in argv:
        return False

    # Check if running in interactive mode
    if not sys.stdin.isatty():
        # Non-interactive environment (CI/CD) - keep existing DB
        print(f"⚠️ Existing database detected: {DB_PATH}")
        print("ℹ️ Running in non-interactive mode - keeping existing database.")
        return False

    print(f"⚠️ Existing database detected: {DB_PATH}")
    try:
        choice = input("Do you want to DELETE and REBUILD the database? (y/N): ").strip().lower()
        return choice == "y"
    except EOFError:
        # If we can't read from stdin, keep the existing DB
        print("ℹ️ Unable to read input - keeping existing database.")
        return False


def main():
    ensure_instance_dir()

    # Optional: Reset DB if requested
    if os.path.exists(DB_PATH):
        if ask_should_reset():
            backup = backup_db(DB_PATH)
            if backup:
                print(f"🧰 Database backup saved at: {backup}")
            try:
                os.remove(DB_PATH)
                print("🗑️ Old database removed. It will be recreated.")
            except Exception as e:
                print(f"❌ Failed to delete database file: {e}")
                print("💡 Make sure no other Flask instance is still running.")
                sys.exit(1)
        else:
            print("✅ Keeping existing database.")

    # Build Flask app and database
    app = create_app()
    try:
        init_database(app)
    except Exception as e:
        print(f"❌ Database initialization FAILED: {e}")
        sys.exit(1)

    # Print mail debug info
    print("📧 MAIL USER:", os.environ.get("MAIL_USERNAME"))

    # Launch Flask server
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Starting server at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
