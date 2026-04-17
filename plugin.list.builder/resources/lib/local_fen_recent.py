"""
Recently watched: union of local library (movies + non-anime shows) + Fen Light watch history.

Local source: VideoLibrary movies and non-anime TV shows with a lastplayed date.
Fen source:   Fen Light's watched.db (progress + watched tables), both movies and shows.
              TMDB IDs are the linking key.

Dedup key: "movie:{tmdb_id}" or "show:{tmdb_id}"; title-based fallback when no TMDB ID.
Local takes priority over Fen in dedup.

Sort: descending by lastplayed (all sources have real timestamps).
"""

import json
import os
import sqlite3

import xbmc
import xbmcvfs

from resources.lib.logger import logger

_FEN_WATCHED_DB = "special://profile/addon_data/plugin.video.fenlight/databases/watched.db"


def _rpc(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        raw = xbmc.executeJSONRPC(json.dumps(payload))
        response = json.loads(raw)
    except Exception as e:
        logger.error("local_fen_recent: JSON-RPC exception: {}".format(e))
        return None
    if "error" in response:
        logger.error("local_fen_recent: RPC error {}: {}".format(method, response["error"]))
        return None
    return response.get("result")


def _read_fen_recent():
    """
    Read Fen Light's watched.db and return recently played item dicts.
    Combines progress (in-progress) and watched (completed) tables.
    For shows: groups episode rows by media_id (show TMDB ID), takes MAX(last_played).
    Returns list of items.
    """
    path = xbmcvfs.translatePath(_FEN_WATCHED_DB)
    if not os.path.exists(path):
        logger.warning("local_fen_recent: watched.db not found at {}".format(path))
        return []

    try:
        con = sqlite3.connect(path, timeout=5)
        cur = con.cursor()

        # Movies: merge progress + watched, newest last_played wins per media_id
        cur.execute("""
            SELECT media_id, title, MAX(last_played) as lp FROM (
                SELECT media_id, title, last_played FROM progress
                WHERE db_type = 'movie' AND media_id != '' AND last_played IS NOT NULL
                UNION ALL
                SELECT media_id, title, last_played FROM watched
                WHERE db_type = 'movie' AND media_id != '' AND last_played IS NOT NULL
            ) GROUP BY media_id
        """)
        movie_rows = cur.fetchall()

        # Shows (grouped from episode rows): merge progress + watched per show TMDB ID
        cur.execute("""
            SELECT media_id, title, MAX(last_played) as lp FROM (
                SELECT media_id, title, last_played FROM progress
                WHERE db_type = 'episode' AND media_id != '' AND last_played IS NOT NULL
                UNION ALL
                SELECT media_id, title, last_played FROM watched
                WHERE db_type = 'episode' AND media_id != '' AND last_played IS NOT NULL
            ) GROUP BY media_id
        """)
        show_rows = cur.fetchall()

        con.close()
    except Exception as e:
        logger.error("local_fen_recent: DB query failed: {}".format(e))
        return []

    items = []
    for tmdb_id, title, lastplayed in movie_rows:
        key = "movie:{}".format(tmdb_id) if tmdb_id else "movie:title:{}".format((title or "").lower())
        url = "plugin://plugin.video.tmdb.bingie.helper/?info=details&tmdb_type=movie&tmdb_id={}".format(tmdb_id)
        items.append({
            "title":      title or "",
            "mediatype":  "movie",
            "file":       url,
            "tmdb_id":    tmdb_id,
            "lastplayed": lastplayed,
            "is_folder":  True,
            "art":        {},
            "year":       None,
            "rating":     None,
            "plot":       None,
            "movieid":    None,
            "tvshowid":   None,
            "uniqueid":   {"tmdb": str(tmdb_id)} if tmdb_id else {},
            "_dedup_key": key,
        })

    for tmdb_id, title, lastplayed in show_rows:
        key = "show:{}".format(tmdb_id) if tmdb_id else "show:title:{}".format((title or "").lower())
        url = "plugin://plugin.video.tmdb.bingie.helper/?info=seasons&tmdb_type=tv&tmdb_id={}".format(tmdb_id)
        items.append({
            "title":      title or "",
            "mediatype":  "tvshow",
            "file":       url,
            "tmdb_id":    tmdb_id,
            "lastplayed": lastplayed,
            "is_folder":  True,
            "art":        {},
            "year":       None,
            "rating":     None,
            "plot":       None,
            "movieid":    None,
            "tvshowid":   None,
            "uniqueid":   {"tmdb": str(tmdb_id)} if tmdb_id else {},
            "_dedup_key": key,
        })

    logger.debug("local_fen_recent: {} movies + {} shows from Fen Light".format(
        len(movie_rows), len(show_rows)))
    return items


def _fetch_local_recent():
    """
    Query VideoLibrary for recently played movies and non-anime TV shows.
    Returns list of item dicts, newest lastplayed first.
    """
    items = []

    # Movies (no tag filter — movies are not typically tagged as Anime)
    movies_result = _rpc("VideoLibrary.GetMovies", {
        "filter": {"field": "lastplayed", "operator": "greaterthan", "value": ""},
        "sort": {"method": "lastplayed", "order": "descending"},
        "properties": ["title", "year", "art", "rating", "lastplayed", "uniqueid", "plot", "file"],
    })
    movie_list = (movies_result or {}).get("movies") or []
    for movie in movie_list:
        uid = movie.get("uniqueid") or {}
        tmdb_id = uid.get("tmdb") or uid.get("tmdb_id")
        movie_id = movie.get("movieid", "")
        title = movie.get("label") or movie.get("title") or ""
        key = "movie:{}".format(tmdb_id) if tmdb_id else "movie:title:{}".format(title.lower())
        items.append({
            "title":      title,
            "mediatype":  "movie",
            "file":       movie.get("file") or "",
            "tmdb_id":    tmdb_id,
            "lastplayed": movie.get("lastplayed") or None,
            "is_folder":  False,
            "art":        movie.get("art") or {},
            "year":       movie.get("year") or None,
            "rating":     movie.get("rating") or None,
            "plot":       movie.get("plot") or None,
            "movieid":    int(movie_id) if movie_id else None,
            "tvshowid":   None,
            "uniqueid":   uid,
            "_dedup_key": key,
        })

    # TV shows — exclude Anime-tagged to avoid overlap with local_otaku_recent widget
    shows_result = _rpc("VideoLibrary.GetTVShows", {
        "filter": {
            "and": [
                {"field": "lastplayed", "operator": "greaterthan", "value": ""},
                {"field": "tag", "operator": "doesnotcontain", "value": "Anime"},
            ]
        },
        "sort": {"method": "lastplayed", "order": "descending"},
        "properties": ["title", "year", "art", "rating", "lastplayed", "uniqueid", "plot"],
    })
    show_list = (shows_result or {}).get("tvshows") or []
    for show in show_list:
        uid = show.get("uniqueid") or {}
        tmdb_id = uid.get("tmdb") or uid.get("tmdb_id")
        show_id = show.get("tvshowid", "")
        title = show.get("label") or show.get("title") or ""
        key = "show:{}".format(tmdb_id) if tmdb_id else "show:title:{}".format(title.lower())
        items.append({
            "title":      title,
            "mediatype":  "tvshow",
            "file":       "videodb://tvshows/titles/{}/".format(show_id),
            "tmdb_id":    tmdb_id,
            "lastplayed": show.get("lastplayed") or None,
            "is_folder":  True,
            "art":        show.get("art") or {},
            "year":       show.get("year") or None,
            "rating":     show.get("rating") or None,
            "plot":       show.get("plot") or None,
            "movieid":    None,
            "tvshowid":   int(show_id) if show_id else None,
            "uniqueid":   uid,
            "_dedup_key": key,
        })

    logger.debug("local_fen_recent: {} movies + {} shows from local library".format(
        len(movie_list), len(show_list)))
    return items


def _merge_and_sort(fen_items, local_items):
    """Dedup (local wins), sort descending by lastplayed. Returns merged list."""
    merged = {}
    for item in fen_items:
        key = item.pop("_dedup_key")
        merged[key] = item
    for item in local_items:
        key = item.pop("_dedup_key")
        merged[key] = item

    all_items = list(merged.values())
    with_ts = sorted(
        [i for i in all_items if i.get("lastplayed")],
        key=lambda x: x["lastplayed"],
        reverse=True,
    )
    without_ts = [i for i in all_items if not i.get("lastplayed")]
    return with_ts + without_ts


def get_recent_movies():
    """Recently watched movies: local library + Fen Light, sorted by lastplayed desc."""
    fen = [i for i in _read_fen_recent() if i.get("mediatype") == "movie"]
    local = [i for i in _fetch_local_recent() if i.get("mediatype") == "movie"]
    items = _merge_and_sort(fen, local)
    logger.info("local_fen_recent: {} movies".format(len(items)))
    return items


def get_recent_series():
    """Recently watched TV series (non-anime): local library + Fen Light, sorted by lastplayed desc."""
    fen = [i for i in _read_fen_recent() if i.get("mediatype") == "tvshow"]
    local = [i for i in _fetch_local_recent() if i.get("mediatype") == "tvshow"]
    items = _merge_and_sort(fen, local)
    logger.info("local_fen_recent: {} series".format(len(items)))
    return items
