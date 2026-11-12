"""Launch the local Super Admin web dashboard and licensing server."""
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Ensure project root is in sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn


def main():
    port = 8000
    host = "127.0.0.1"
    url = f"http://{host}:{port}/admin"

    print("=" * 65)
    print("  PHARMACY MANAGEMENT - LOCAL SUPER ADMIN WEB SERVER")
    print("=" * 65)
    print(f"  Dashboard URL:     {url}")
    print(f"  Sign-in URL:       http://{host}:{port}/admin/sign-in")
    print(f"  Health Check:      http://{host}:{port}/health")
    print("=" * 65)
    print("  Opening browser automatically... (Press Ctrl+C to stop)\n")

    def open_browser():
        time.sleep(1.2)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(
        "super_admin.backend.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
