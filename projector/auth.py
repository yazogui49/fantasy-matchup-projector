from __future__ import annotations

import json
import logging

from yahoo_fantasy_api import Game
from yahoo_oauth import OAuth2

from .config import GAME_CODE, OAUTH_FILE, yahoo_credentials

logging.getLogger("yahoo_oauth").setLevel(logging.WARNING)


def _ensure_oauth_file() -> None:
    """Seed oauth2.json from .env on first run; yahoo_oauth adds tokens to it after login."""
    if OAUTH_FILE.exists():
        return
    key, secret, redirect = yahoo_credentials()
    OAUTH_FILE.write_text(
        json.dumps(
            {"consumer_key": key, "consumer_secret": secret, "callback_uri": redirect},
            indent=2,
        )
    )
    OAUTH_FILE.chmod(0o600)


def get_session() -> OAuth2:
    """Return an authenticated session. First call opens the browser for consent;
    afterwards the saved refresh token is used and renewed automatically."""
    _ensure_oauth_file()
    sc = OAuth2(None, None, from_file=str(OAUTH_FILE))
    if not sc.token_is_valid():
        sc.refresh_access_token()
    return sc


def list_leagues(sc: OAuth2) -> list[str]:
    return Game(sc, GAME_CODE).league_ids()
