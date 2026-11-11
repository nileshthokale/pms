"""Vercel ASGI entrypoint; serves the existing license/device API and Super Admin."""
from license_server.app import create_app

app = create_app()
