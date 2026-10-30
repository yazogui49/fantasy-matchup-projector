from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OAUTH_FILE = ROOT / "oauth2.json"
CACHE_DIR = ROOT / "cache"
GAME_CODE = "nba"


def yahoo_credentials() -> tuple[str, str, str]:
    key = os.getenv("YAHOO_CLIENT_ID")
    secret = os.getenv("YAHOO_CLIENT_SECRET")
    redirect = os.getenv("YAHOO_REDIRECT_URI", "https://localhost:8080")
    if not key or not secret:
        raise SystemExit(
            "Missing YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET. "
            "Copy .env.example to .env and fill them in."
        )
    return key, secret, redirect
