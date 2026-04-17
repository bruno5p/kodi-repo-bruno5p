"""
Recently watched: union of local anime library + Otaku watch history.

Local source: VideoLibrary TV shows tagged "Anime" with a lastplayed date.
Otaku source: watch_history.json read directly from Otaku's addon_data folder,
              enriched with lastplayed timestamps from VideoLibrary (via MAL ID
              lookup) where the show exists in the local library.

Deduplication key: MAL ID when available, lowercased title otherwise.
Local takes priority over Otaku in dedup.

Sort: items with a lastplayed timestamp come first (descending), then
items not in the local library at all, in their original Otaku history order
(most recent first by array index).
"""

import glob
import json
import os
import re
import sqlite3

import xbmc
import xbmcvfs

from resources.lib.logger import logger

_OTAKU_HISTORY_PATH = "special://profile/addon_data/plugin.video.otaku.testing/watch_history.json"


def _rpc(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        raw = xbmc.executeJSONRPC(json.dumps(payload))
        response = json.loads(raw)
    except Exception as e:
        logger.error("local_otaku_recent: JSON-RPC exception: {}".format(e))
        return None
    if "error" in response:
        logger.error("local_otaku_recent: RPC error {}: {}".format(method, response["error"]))
        return None
    return response.get("result")


_OTAKU_MAL_RE = re.compile(r'/play(?:_movie)?/(\d+)/')


def _build_mal_lastplayed_map():
    """
    Read Kodi's MyVideos DB directly to get lastPlayed timestamps for Otaku
    plugin files. These files are tracked in the 'files' table but are NOT
    linked to library episodes, so VideoLibrary JSON-RPC calls return nothing
    for them. The strFilename column holds the full plugin:// URL.

    Returns {int_mal_id: lastplayed_str} keeping the most recent date per show.
    Falls back to {} on any error.
    """
    db_dir = xbmcvfs.translatePath("special://database/")
    db_files = sorted(glob.glob(os.path.join(db_dir, "MyVideos*.db")), reverse=True)
    if not db_files:
        logger.warning("local_otaku_recent: MyVideos DB not found in {}".format(db_dir))
        return {}

    try:
        con = sqlite3.connect(db_files[0], timeout=5)
        cur = con.cursor()
        cur.execute("""
            SELECT f.strFilename, f.lastPlayed
            FROM files f
            JOIN path p ON f.idPath = p.idPath
            WHERE p.strPath LIKE '%plugin.video.otaku%'
              AND f.lastPlayed IS NOT NULL AND f.lastPlayed != ''
        """)
        rows = cur.fetchall()
        con.close()
    except Exception as e:
        logger.error("local_otaku_recent: DB query failed: {}".format(e))
        return {}

    mal_map = {}
    for filename, lastplayed in rows:
        m = _OTAKU_MAL_RE.search(filename or "")
        if not m:
            continue
        try:
            mal_id = int(m.group(1))
        except (ValueError, TypeError):
            continue
        if lastplayed and (mal_id not in mal_map or lastplayed > mal_map[mal_id]):
            mal_map[mal_id] = lastplayed

    logger.debug("local_otaku_recent: lastplayed map: {} MAL IDs".format(len(mal_map)))
    return mal_map


def _fetch_local_recent():
    """
    Query VideoLibrary for recently played TV shows tagged "Anime".
    Returns list of item dicts, newest lastplayed first.
    """
    result = _rpc("VideoLibrary.GetTVShows", {
        "filter": {
            "and": [
                {"field": "lastplayed", "operator": "greaterthan", "value": ""},
                {"field": "tag", "operator": "contains", "value": "Anime"},
            ]
        },
        "sort": {"method": "lastplayed", "order": "descending"},
        "properties": ["title", "year", "art", "rating", "lastplayed", "uniqueid", "plot"],
    })
    if result is None:
        return []

    raw = result.get("tvshows") or []
    logger.debug("local_otaku_recent: VideoLibrary returned {} anime with lastplayed".format(len(raw)))

    items = []
    for show in raw:
        uid = show.get("uniqueid") or {}
        mal_id = uid.get("mal") or uid.get("mal_id")
        try:
            mal_id = int(mal_id) if mal_id else None
        except (ValueError, TypeError):
            mal_id = None
        show_id = show.get("tvshowid", "")
        title = show.get("label") or show.get("title") or ""
        dedup_key = "mal:{}".format(mal_id) if mal_id else "title:{}".format(title.lower())
        items.append({
            "title":      title,
            "mediatype":  "tvshow",
            "file":       "videodb://tvshows/titles/{}/".format(show_id),
            "year":       show.get("year") or None,
            "art":        show.get("art") or {},
            "rating":     show.get("rating") or None,
            "lastplayed": show.get("lastplayed") or None,
            "plot":       show.get("plot") or None,
            "is_folder":  True,
            "mal_id":     mal_id,
            "tvshowid":   int(show_id) if show_id else None,
            "uniqueid":   uid,
            "_dedup_key": dedup_key,
            "_otaku_idx": None,
        })
    return items


def _fetch_otaku_recent(mal_lastplayed_map=None):
    """
    Read Otaku's watch_history.json directly and return item dicts.
    Index 0 in the file = most recently watched.
    Each entry is enriched with a real lastplayed timestamp from mal_lastplayed_map
    when the show is present in the local VideoLibrary.
    """
    if mal_lastplayed_map is None:
        mal_lastplayed_map = {}
    path = xbmcvfs.translatePath(_OTAKU_HISTORY_PATH)
    if not os.path.exists(path):
        logger.warning("local_otaku_recent: watch_history.json not found at {}".format(path))
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (IOError, ValueError) as e:
        logger.error("local_otaku_recent: failed to read watch_history.json: {}".format(e))
        return []

    history = data.get("history") or []
    logger.debug("local_otaku_recent: {} entries in otaku watch_history.json".format(len(history)))

    items = []
    for idx, entry in enumerate(history):
        uid = entry.get("UniqueIDs") or {}
        mal_id = uid.get("mal_id") or uid.get("mal")
        try:
            mal_id = int(mal_id) if mal_id else None
        except (ValueError, TypeError):
            mal_id = None

        title = entry.get("title") or ""
        episodes = entry.get("episodes", 0)
        if episodes == 1:
            file_url = "plugin://plugin.video.otaku.testing/play_movie/{}/".format(mal_id) if mal_id else ""
        else:
            file_url = "plugin://plugin.video.otaku.testing/animes/{}/".format(mal_id) if mal_id else ""

        dedup_key = "mal:{}".format(mal_id) if mal_id else "title:{}".format(title.lower())

        # Build art dict from Otaku entry fields
        poster = entry.get("poster") or entry.get("tvshow.poster") or ""
        art = {}
        if poster:
            art["poster"] = poster
            art["thumb"] = poster
        fanart = entry.get("fanart")
        if isinstance(fanart, list):
            fanart = fanart[0] if fanart else ""
        if fanart:
            art["fanart"] = fanart
        banner = entry.get("banner")
        if isinstance(banner, list):
            banner = banner[0] if banner else ""
        if banner:
            art["banner"] = banner
        for key in ("clearart", "clearlogo", "landscape"):
            val = entry.get(key)
            if isinstance(val, list):
                val = val[0] if val else ""
            if val:
                art[key] = val

        # Normalise rating: Otaku stores as {"score": X, "votes": Y}
        raw_rating = entry.get("rating")
        if isinstance(raw_rating, dict):
            rating = raw_rating.get("score") or raw_rating.get("rating") or None
        else:
            rating = raw_rating or None

        # Enrich with real lastplayed from VideoLibrary if show is in the local library
        lastplayed = mal_lastplayed_map.get(mal_id) if mal_id else None

        items.append({
            "title":      title,
            "mediatype":  "tvshow",
            "file":       file_url,
            "year":       entry.get("year") or None,
            "art":        art,
            "rating":     rating,
            "lastplayed": lastplayed,
            "plot":       entry.get("plot") or None,
            "is_folder":  True,
            "mal_id":     mal_id,
            "uniqueid":   {k: str(v) for k, v in uid.items() if v},
            "_dedup_key": dedup_key,
            "_otaku_idx": idx,  # 0 = most recently watched
        })

    return items


def get_recent_items():
    """
    Merge local recently played anime + Otaku watch history, dedup by MAL ID (or title).
    Local takes priority. Sort:
      - Items with a lastplayed timestamp: descending (most recent first).
        Otaku items in the local library are enriched with real timestamps.
      - Items not in the local library at all: appended after, in Otaku history
        order (index 0 = most recent).
    """
    mal_lastplayed_map = _build_mal_lastplayed_map()
    local = _fetch_local_recent()
    otaku = _fetch_otaku_recent(mal_lastplayed_map)

    merged = {}
    # Lower priority first (otaku), then local overwrites
    for item in otaku:
        key = item.pop("_dedup_key")
        merged[key] = item
    for item in local:
        key = item.pop("_dedup_key")
        merged[key] = item

    all_items = list(merged.values())

    with_timestamp = sorted(
        [i for i in all_items if i.get("lastplayed")],
        key=lambda x: x["lastplayed"],
        reverse=True,
    )
    without_timestamp = sorted(
        [i for i in all_items if not i.get("lastplayed")],
        key=lambda x: x.get("_otaku_idx") if x.get("_otaku_idx") is not None else 9999,
    )

    items = with_timestamp + without_timestamp

    for item in items:
        item.pop("_otaku_idx", None)

    logger.info("local_otaku_recent: {} items ({} with timestamp, {} otaku-only)".format(
        len(items), len(with_timestamp), len(without_timestamp)
    ))
    return items
