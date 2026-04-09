"""
Fetches and deduplicates items from three currently-watching sources,
using MAL ID as the dedup key.

Priority: Local library > Otaku watchlist > MAL watch history
"""

import json
import re

import xbmc

from resources.lib.logger import logger

_OTAKU_WATCHING_URL = "plugin://plugin.video.otaku.testing/watch_history/"
_MAL_HISTORY_URL    = "plugin://plugin.video.otaku.testing/watchlist_status_type/mal/watching"
# Matches Otaku URL patterns: /animes/12345/, /animes/12345, /play/12345/1, /play_movie/12345/, /watchlist_to_ep/12345/1
_MAL_ID_RE = re.compile(r'/(?:animes?|play(?:_movie)?|watchlist_to_ep)/(\d+)')


def _rpc(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        raw = xbmc.executeJSONRPC(json.dumps(payload))
        response = json.loads(raw)
    except Exception as e:
        logger.error("otaku_combined: JSON-RPC exception: {}".format(e))
        return None
    if "error" in response:
        logger.error("otaku_combined: RPC error {}: {}".format(method, response["error"]))
        return None
    return response.get("result")


def _get_directory(plugin_url):
    """Return Files.GetDirectory items list or []."""
    result = _rpc("Files.GetDirectory", {
        "directory": plugin_url,
        "media": "video",
        "properties": ["file", "title", "art", "year", "rating"],
    })
    if result is None:
        logger.warning("otaku_combined: Files.GetDirectory returned None for {}".format(plugin_url))
        return []
    files = result.get("files") or []
    logger.debug("otaku_combined: got {} files from {}".format(len(files), plugin_url))
    for f in files[:5]:
        logger.debug("otaku_combined:   file={} label={}".format(f.get("file", ""), f.get("label", "")))
    return files


def _extract_mal_id(path):
    """Extract MAL ID int from a plugin:// path like .../animes/12345/... or None."""
    m = _MAL_ID_RE.search(path or "")
    return int(m.group(1)) if m else None


def _fetch_local_watching():
    """
    Query VideoLibrary for in-progress TV shows that have a MAL uniqueid.
    Returns dict: {mal_id: item_dict}
    """
    result = _rpc("VideoLibrary.GetTVShows", {
        "filter": {"field": "inprogress", "operator": "true", "value": ""},
        "properties": ["title", "year", "art", "rating", "dateadded", "lastplayed", "uniqueid"],
    })
    if result is None:
        return {}

    raw = result.get("tvshows") or []
    logger.debug("otaku_combined: VideoLibrary returned {} inprogress tvshows".format(len(raw)))

    seen = {}
    for show in raw:
        uid = show.get("uniqueid") or {}
        mal_id = uid.get("mal") or uid.get("mal_id")
        if not mal_id:
            continue
        try:
            mal_id = int(mal_id)
        except (ValueError, TypeError):
            continue
        show_id = show.get("tvshowid", "")
        seen[mal_id] = {
            "title":      show.get("label") or show.get("title") or "",
            "mediatype":  "tvshow",
            "file":       "videodb://tvshows/titles/{}/".format(show_id),
            "year":       show.get("year") or None,
            "art":        show.get("art") or {},
            "rating":     show.get("rating") or None,
            "dateadded":  show.get("dateadded") or None,
            "lastplayed": show.get("lastplayed") or None,
            "is_folder":  True,
            "mal_id":     mal_id,
            "tvshowid":   int(show_id) if show_id else None,
        }
    logger.debug("otaku_combined: {} local watching".format(len(seen)))
    return seen


def _fetch_plugin_watching(plugin_url, source_name):
    """
    Fetch items from an Otaku plugin directory.
    Returns dict: {mal_id: item_dict}
    """
    files = _get_directory(plugin_url)
    seen = {}
    for f in files:
        path = f.get("file", "")
        mal_id = _extract_mal_id(path)
        if not mal_id:
            continue
        seen[mal_id] = {
            "title":      f.get("label") or f.get("title") or "",
            "mediatype":  "tvshow",
            "file":       path,
            "year":       f.get("year") or None,
            "art":        f.get("art") or {},
            "rating":     f.get("rating") or None,
            "dateadded":  None,
            "lastplayed": f.get("lastplayed") or None,
            "is_folder":  True,
            "mal_id":     mal_id,
        }
    logger.debug("otaku_combined: {} items from {}".format(len(seen), source_name))
    return seen


def get_combined_items(entry=None):
    """
    Fetch enabled sources, deduplicate by MAL ID, return merged item list.
    Priority: local > otaku watchlist > MAL watch history.
    Sorted by lastplayed descending.

    entry: optional list config dict — reads entry["sources"] for per-source toggles.
           Missing keys default to True (enabled).
    """
    sources = (entry or {}).get("sources", {})
    include_local  = sources.get("local", True)
    include_otaku  = sources.get("otaku_watching", True)
    include_mal    = sources.get("mal_watching", True)

    local   = _fetch_local_watching() if include_local else {}
    otaku   = _fetch_plugin_watching(_OTAKU_WATCHING_URL, "otaku_watching") if include_otaku else {}
    history = _fetch_plugin_watching(_MAL_HISTORY_URL, "mal_history") if include_mal else {}

    merged = {}
    # lowest priority first so higher-priority sources overwrite
    for source in (history, otaku, local):
        for mal_id, item in source.items():
            merged[mal_id] = item

    items = list(merged.values())
    items.sort(key=lambda x: x.get("lastplayed") or "", reverse=True)
    logger.info("otaku_combined: {} combined items after dedup".format(len(items)))
    return items
