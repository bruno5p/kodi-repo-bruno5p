"""
MAL API v2 client — read and update anime list status.
"""
import json

try:
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError
except ImportError:
    from urllib2 import urlopen, Request, HTTPError

try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode

from resources.lib.logger import logger
from resources.lib import auth

MAL_API_BASE = "https://api.myanimelist.net/v2"

# MAL watch status values
STATUS_WATCHING = "watching"
STATUS_COMPLETED = "completed"
STATUS_ON_HOLD = "on_hold"
STATUS_DROPPED = "dropped"
STATUS_PLAN_TO_WATCH = "plan_to_watch"

STATUS_LABELS = {
    STATUS_WATCHING: "Watching",
    STATUS_COMPLETED: "Completed",
    STATUS_ON_HOLD: "On Hold",
    STATUS_DROPPED: "Dropped",
    STATUS_PLAN_TO_WATCH: "Plan to Watch",
}


def _request(method, path, data=None, access_token=None, retry=True):
    """Make an authenticated MAL API request."""
    token = access_token or auth.get_access_token()
    if not token:
        logger.warning("mal_api: no access token available")
        return None

    url = "{}{}".format(MAL_API_BASE, path)
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Content-Type": "application/x-www-form-urlencoded"
    }

    body = urlencode(data).encode("utf-8") if data else None
    req = Request(url, data=body, headers=headers)
    req.get_method = lambda: method

    try:
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 401 and retry:
            logger.info("mal_api: 401 received, attempting token refresh")
            new_token = auth.refresh_tokens()
            if new_token:
                return _request(method, path, data, new_token, retry=False)
        body = e.read().decode("utf-8", errors="replace")
        logger.error("mal_api: HTTP {} for {}: {}".format(e.code, path, body[:300]))
        return None
    except Exception as e:
        logger.error("mal_api: request exception for {}: {}".format(path, e))
        return None


def get_anime_list_status(mal_id):
    """
    Fetch the current user's watch status for an anime.
    Returns dict with keys: status, score, num_episodes_watched, or None.
    """
    result = _request("GET", "/anime/{}?fields=my_list_status".format(mal_id))
    if result:
        return result.get("my_list_status")
    return None


def update_anime_status(mal_id, status=None, score=None, num_watched=None):
    """
    Update the user's watch status for an anime.
    Only provided fields are sent.
    Returns the updated status dict or None on failure.
    """
    data = {}
    if status is not None:
        data["status"] = status
    if score is not None:
        data["score"] = str(score)
    if num_watched is not None:
        data["num_watched_episodes"] = str(num_watched)

    if not data:
        logger.warning("mal_api: update_anime_status called with no fields to update")
        return None

    logger.debug("mal_api: updating mal_id={} data={}".format(mal_id, data))
    return _request("PATCH", "/anime/{}/my_list_status".format(mal_id), data=data)
