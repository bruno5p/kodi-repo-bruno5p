"""
MAL authentication for MAL Manager.

Token priority:
  1. plugin.video.otaku.testing settings (mal.token / mal.refresh / mal.expiry)
     — if the user is already logged into Otaku no re-authentication is needed.
  2. Own addon settings (access_token / refresh_token) — set by run_auth_flow().

Auth flow (fallback) mirrors Otaku Testing's method:
  - Visit https://armkai.vercel.app/api/mal → authorise → MAL redirects to
    https://myanimelist.net/?code=<code>&state=<pkce_verifier>
  - Paste that full redirect URL when prompted.
  - code + state (= PKCE verifier, plain method) are exchanged for tokens.
  - Tokens are stored in Otaku's settings when possible, and always in our own.
"""
import json
import time

import xbmc
import xbmcgui
import xbmcaddon

try:
    from urllib.request import urlopen, Request
    from urllib.parse import urlencode, urlparse, parse_qsl
    from urllib.error import HTTPError
except ImportError:
    from urllib2 import urlopen, Request, HTTPError
    from urlparse import urlparse, parse_qsl
    from urllib import urlencode

from resources.lib.logger import logger

ADDON = xbmcaddon.Addon()

_OTAKU_ADDON_ID = 'plugin.video.otaku.testing'
# Otaku Testing's registered MAL client_id (plain PKCE, no secret required)
_CLIENT_ID = 'a8d85a4106b259b8c9470011ce2f76bc'
_TOKEN_URL = 'https://myanimelist.net/v1/oauth2/token'
# Otaku's auth helper — generates the PKCE verifier/challenge and redirects
# to myanimelist.net/v1/oauth2/authorize, passing the verifier as both
# code_challenge (plain) and state so it comes back in the redirect URL.
_AUTH_HELPER_URL = 'https://armkai.vercel.app/api/mal'


# ── Token helpers ─────────────────────────────────────────────────────────────

def get_access_token():
    """
    Return a valid MAL access token, or None if not authenticated.
    Tries Otaku Testing first, then own stored token.
    """
    token = _get_otaku_token()
    if token:
        return token

    token = ADDON.getSetting('access_token').strip()
    if token:
        logger.debug("auth: using own stored access token")
        return token

    return None


def get_username():
    """Return the MAL username if available (from Otaku or own settings)."""
    try:
        otaku = xbmcaddon.Addon(_OTAKU_ADDON_ID)
        username = otaku.getSetting('mal.username').strip()
        if username:
            return username
    except Exception:
        pass
    return ADDON.getSetting('username').strip() or None


def _get_otaku_token():
    """Read and validate the MAL token from Otaku Testing's settings."""
    try:
        otaku = xbmcaddon.Addon(_OTAKU_ADDON_ID)
        token = otaku.getSetting('mal.token').strip()
        if not token:
            return None

        expiry_str = otaku.getSetting('mal.expiry').strip()
        expiry = int(expiry_str) if expiry_str and expiry_str.isdigit() else 0
        # Refresh if expired or expiring within 60 s
        if expiry and time.time() >= expiry - 60:
            logger.info("auth: Otaku token expired, attempting refresh")
            refreshed = _refresh_via_otaku(otaku)
            return refreshed  # None if refresh failed

        logger.info("auth: using MAL token from {}".format(_OTAKU_ADDON_ID))
        return token
    except Exception as e:
        logger.debug("auth: could not read from {}: {}".format(_OTAKU_ADDON_ID, e))
        return None


def _refresh_via_otaku(otaku):
    """Refresh using Otaku's refresh token. Writes updated tokens back. Returns new access token or None."""
    try:
        refresh = otaku.getSetting('mal.refresh').strip()
        if not refresh:
            return None
        new_token, new_refresh, expires_in = _do_refresh(refresh)
        if new_token:
            otaku.setSetting('mal.token', new_token)
            otaku.setSetting('mal.refresh', new_refresh)
            otaku.setSetting('mal.expiry', str(int(time.time()) + int(expires_in)))
            logger.info("auth: Otaku token refreshed successfully")
            return new_token
    except Exception as e:
        logger.debug("auth: Otaku refresh failed: {}".format(e))
    return None


def _do_refresh(refresh_token):
    """
    Call the MAL token endpoint with grant_type=refresh_token.
    Returns (access_token, refresh_token, expires_in) or (None, None, 0) on failure.
    """
    data = urlencode({
        'client_id': _CLIENT_ID,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
    }).encode('utf-8')
    req = Request(_TOKEN_URL, data=data, headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        resp = urlopen(req, timeout=15)
        tokens = json.loads(resp.read().decode('utf-8'))
        return (
            tokens.get('access_token', ''),
            tokens.get('refresh_token', refresh_token),
            tokens.get('expires_in', 2592000),
        )
    except Exception as e:
        logger.error("auth: token refresh HTTP call failed: {}".format(e))
        return None, None, 0


def refresh_tokens():
    """
    Attempt token refresh.  Called automatically by mal_api on 401.
    Tries Otaku's refresh token first, then own stored refresh token.
    Returns new access token or None.
    """
    # 1. Otaku refresh
    try:
        otaku = xbmcaddon.Addon(_OTAKU_ADDON_ID)
        new_token = _refresh_via_otaku(otaku)
        if new_token:
            # Mirror into own settings so mal_api can always read a fresh token
            ADDON.setSetting('access_token', new_token)
            return new_token
    except Exception:
        pass

    # 2. Own refresh token
    own_refresh = ADDON.getSetting('refresh_token').strip()
    if not own_refresh:
        return None
    new_token, new_refresh, expires_in = _do_refresh(own_refresh)
    if new_token:
        ADDON.setSetting('access_token', new_token)
        ADDON.setSetting('refresh_token', new_refresh)
        logger.info("auth: own token refreshed successfully")
        return new_token
    return None


# ── Auth flow ─────────────────────────────────────────────────────────────────

def run_auth_flow():
    """
    PKCE auth flow matching Otaku Testing's UX:
      1. Show the armkai helper URL and open it in the default browser.
      2. User authorises on MAL → MAL redirects to myanimelist.net with ?code=&state=
      3. User pastes the redirect URL.
      4. Extract code + state (= PKCE verifier, plain method) and exchange for tokens.
      5. Store tokens in Otaku Testing settings (if available) and own settings.
    """
    # ── Step 1: instructions ──────────────────────────────────────────────────
    xbmcgui.Dialog().ok(
        "MAL Manager — Authorize",
        "[B]Open this link in a browser:[/B][CR]"
        "[COLOR deepskyblue]{}[/COLOR][CR][CR]"
        "After authorising, MAL will redirect to its homepage.[CR]"
        "Copy & paste the full redirect URL "
        "(e.g. [COLOR deepskyblue]https://myanimelist.net/?code=...[/COLOR]) "
        "in the next step.".format(_AUTH_HELPER_URL)
    )

    # ── Step 2: try to open browser ───────────────────────────────────────────
    xbmc.executebuiltin("OpenURL({})".format(_AUTH_HELPER_URL))

    # ── Step 3: get redirect URL ──────────────────────────────────────────────
    redirect_url = xbmcgui.Dialog().input(
        "Paste the redirect URL here:",
        type=xbmcgui.INPUT_ALPHANUM
    )
    if not redirect_url:
        logger.warning("auth: user cancelled — no redirect URL provided")
        return

    redirect_url = redirect_url.strip()

    # ── Step 4: parse code and verifier ──────────────────────────────────────
    try:
        parsed = urlparse(redirect_url)
        params = dict(parse_qsl(parsed.query))
        code = params.get('code', '').strip()
        verifier = params.get('state', '').strip()
    except Exception as e:
        logger.error("auth: could not parse redirect URL: {}".format(e))
        xbmcgui.Dialog().ok(
            "MAL Manager",
            "Could not parse the URL.[CR]Make sure you pasted the full redirect URL."
        )
        return

    if not code or not verifier:
        xbmcgui.Dialog().ok(
            "MAL Manager",
            "Could not find the authorisation code.[CR]"
            "Paste the complete redirect URL including [B]?code=...[/B]"
        )
        return

    # ── Step 5: exchange code for tokens ──────────────────────────────────────
    logger.debug("auth: exchanging code for tokens (code_verifier=state)")
    data = urlencode({
        'client_id': _CLIENT_ID,
        'code': code,
        'code_verifier': verifier,
        'grant_type': 'authorization_code',
    }).encode('utf-8')
    req = Request(
        _TOKEN_URL, data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    try:
        resp = urlopen(req, timeout=15)
        tokens = json.loads(resp.read().decode('utf-8'))
    except HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        logger.error("auth: token exchange failed: {} {}".format(e.code, body))
        xbmcgui.Dialog().ok("MAL Manager", "Authorisation failed.[CR]{}".format(body[:200]))
        return
    except Exception as e:
        logger.error("auth: token exchange exception: {}".format(e))
        xbmcgui.Dialog().ok("MAL Manager", "Authorisation failed.[CR]{}".format(str(e)))
        return

    access_token = tokens.get('access_token', '')
    refresh_token_val = tokens.get('refresh_token', '')
    expires_in = tokens.get('expires_in', 2592000)

    if not access_token:
        xbmcgui.Dialog().ok("MAL Manager", "No access token received.[CR]Please try again.")
        return

    # ── Step 6: fetch username and store tokens ────────────────────────────────
    username = _fetch_username(access_token) or ''

    # Prefer storing in Otaku so its watchlist also benefits immediately
    _store_in_otaku(access_token, refresh_token_val, expires_in, username)

    ADDON.setSetting('access_token', access_token)
    ADDON.setSetting('refresh_token', refresh_token_val)
    ADDON.setSetting('username', username)

    logger.info("auth: authenticated successfully as '{}'".format(username or '(unknown)'))
    msg = "Authenticated as {}".format(username) if username else "Authenticated successfully!"
    xbmcgui.Dialog().notification("MAL Manager", msg, xbmcgui.NOTIFICATION_INFO, 3000)


def _fetch_username(access_token):
    """Call /users/@me to get the MAL username. Returns str or None."""
    try:
        req = Request(
            'https://api.myanimelist.net/v2/users/@me?fields=name',
            headers={'Authorization': 'Bearer {}'.format(access_token)}
        )
        resp = urlopen(req, timeout=10)
        data = json.loads(resp.read().decode('utf-8'))
        return data.get('name', '')
    except Exception as e:
        logger.debug("auth: could not fetch username: {}".format(e))
        return None


def _store_in_otaku(access_token, refresh_token_val, expires_in, username):
    """Best-effort: write tokens into Otaku Testing's settings."""
    try:
        otaku = xbmcaddon.Addon(_OTAKU_ADDON_ID)
        otaku.setSetting('mal.token', access_token)
        otaku.setSetting('mal.refresh', refresh_token_val)
        otaku.setSetting('mal.expiry', str(int(time.time()) + int(expires_in)))
        if username:
            otaku.setSetting('mal.username', username)
        logger.info("auth: tokens also stored in {}".format(_OTAKU_ADDON_ID))
    except Exception as e:
        logger.debug("auth: could not store in {}: {}".format(_OTAKU_ADDON_ID, e))
