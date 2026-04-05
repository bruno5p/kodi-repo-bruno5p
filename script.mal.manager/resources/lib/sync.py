"""
Sync watch status between Kodi local library and MyAnimeList.

Rules:
  Update from MAL:       if MAL=completed and Kodi=not watched → mark Kodi watched (status never goes lower)
  Update to MAL:         if Kodi=watched and MAL≠completed    → update MAL to completed (status never goes lower)
  Force sync from MAL:   apply MAL status to Kodi regardless of local status (overrides local if higher)
"""
import json
import xbmc

from resources.lib.logger import logger
from resources.lib import mal_api


# ── Kodi JSON-RPC helper ──────────────────────────────────────────────────────

def _rpc(method, params=None):
    request = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params:
        request["params"] = params
    response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    return response.get("result")


# ── Library query ─────────────────────────────────────────────────────────────

def _get_library_anime():
    """
    Return all Kodi library items (tvshows + movies) that carry a MAL unique ID.

    Each entry is a dict:
      type             : "tvshow" | "movie"
      kodi_id          : int
      title            : str
      mal_id           : str
      watched          : bool  (all episodes watched for shows; playcount>0 for movies)
      total_episodes   : int
      watched_episodes : int
    """
    items = []

    # ── TV Shows ──────────────────────────────────────────────────────────────
    result = _rpc("VideoLibrary.GetTVShows", {
        "properties": ["title", "uniqueid", "episode", "watchedepisodes"]
    })
    if result and "tvshows" in result:
        for show in result["tvshows"]:
            mal_id = _extract_mal_id(show.get("uniqueid", {}))
            if not mal_id:
                continue
            total = show.get("episode", 0)
            watched_ep = show.get("watchedepisodes", 0)
            items.append({
                "type": "tvshow",
                "kodi_id": show["tvshowid"],
                "title": show.get("title", ""),
                "mal_id": mal_id,
                "watched": total > 0 and watched_ep >= total,
                "total_episodes": total,
                "watched_episodes": watched_ep,
            })

    # ── Movies ────────────────────────────────────────────────────────────────
    result = _rpc("VideoLibrary.GetMovies", {
        "properties": ["title", "uniqueid", "playcount"]
    })
    if result and "movies" in result:
        for movie in result["movies"]:
            mal_id = _extract_mal_id(movie.get("uniqueid", {}))
            if not mal_id:
                continue
            items.append({
                "type": "movie",
                "kodi_id": movie["movieid"],
                "title": movie.get("title", ""),
                "mal_id": mal_id,
                "watched": movie.get("playcount", 0) > 0,
                "total_episodes": 1,
                "watched_episodes": 1 if movie.get("playcount", 0) > 0 else 0,
            })

    logger.info("sync: found {} library items with a MAL ID".format(len(items)))
    return items


def _extract_mal_id(unique_ids):
    """Return the MAL ID string from a Kodi uniqueid dict, or None."""
    for key in ("mal", "mal_id"):
        val = unique_ids.get(key)
        if val and str(val).strip().isdigit():
            return str(val).strip()
    return None


# ── Kodi write helpers ────────────────────────────────────────────────────────

def _mark_kodi_watched(item):
    """Mark a library item as fully watched in Kodi."""
    if item["type"] == "movie":
        _rpc("VideoLibrary.SetMovieDetails", {
            "movieid": item["kodi_id"],
            "playcount": 1,
        })
        logger.debug("sync: movie '{}' marked watched".format(item["title"]))

    elif item["type"] == "tvshow":
        result = _rpc("VideoLibrary.GetEpisodes", {
            "tvshowid": item["kodi_id"],
            "properties": ["playcount"],
        })
        if result and "episodes" in result:
            for ep in result["episodes"]:
                if ep.get("playcount", 0) == 0:
                    _rpc("VideoLibrary.SetEpisodeDetails", {
                        "episodeid": ep["episodeid"],
                        "playcount": 1,
                    })
            logger.debug("sync: tvshow '{}' all episodes marked watched".format(item["title"]))


# ── Public sync functions ─────────────────────────────────────────────────────

def sync_from_mal(on_progress=None, is_cancelled=None):
    """
    Pull completed status from MAL into the Kodi library.
    MAL completed + Kodi not watched → mark Kodi watched.
    Status never goes lower.

    on_progress(current, total, title) — optional progress callback
    is_cancelled()                     — optional cancellation check

    Returns (updated, skipped, errors).
    """
    items = _get_library_anime()
    total = len(items)
    updated = skipped = errors = 0

    for i, item in enumerate(items):
        if is_cancelled and is_cancelled():
            logger.info("sync_from_mal: cancelled by user at item {}/{}".format(i, total))
            break

        if on_progress:
            on_progress(i, total, item["title"])

        if item["watched"]:
            # Already watched locally — nothing to update
            skipped += 1
            continue

        mal_status_data = mal_api.get_anime_list_status(item["mal_id"])
        if mal_status_data is None:
            skipped += 1
            continue

        if mal_status_data.get("status") == mal_api.STATUS_COMPLETED:
            logger.info("sync_from_mal: '{}' (mal_id={}) completed on MAL, updating Kodi".format(
                item["title"], item["mal_id"]))
            try:
                _mark_kodi_watched(item)
                updated += 1
            except Exception as exc:
                logger.error("sync_from_mal: failed to update '{}': {}".format(item["title"], exc))
                errors += 1
        else:
            skipped += 1

    logger.info("sync_from_mal: done — updated={} skipped={} errors={}".format(updated, skipped, errors))
    return updated, skipped, errors


def sync_to_mal(on_progress=None, is_cancelled=None):
    """
    Push watched status from Kodi library to MAL.
    Kodi watched + MAL not completed → update MAL to completed.
    Status never goes lower.

    Returns (updated, skipped, errors).
    """
    items = _get_library_anime()
    total = len(items)
    updated = skipped = errors = 0

    for i, item in enumerate(items):
        if is_cancelled and is_cancelled():
            logger.info("sync_to_mal: cancelled by user at item {}/{}".format(i, total))
            break

        if on_progress:
            on_progress(i, total, item["title"])

        if not item["watched"]:
            # Not watched locally — nothing to push
            skipped += 1
            continue

        mal_status_data = mal_api.get_anime_list_status(item["mal_id"])
        if mal_status_data and mal_status_data.get("status") == mal_api.STATUS_COMPLETED:
            # Already completed on MAL — no need to update
            skipped += 1
            continue

        logger.info("sync_to_mal: '{}' (mal_id={}) watched locally, updating MAL to completed".format(
            item["title"], item["mal_id"]))
        result = mal_api.update_anime_status(item["mal_id"], status=mal_api.STATUS_COMPLETED)
        if result:
            updated += 1
        else:
            logger.error("sync_to_mal: failed to update '{}' on MAL".format(item["title"]))
            errors += 1

    logger.info("sync_to_mal: done — updated={} skipped={} errors={}".format(updated, skipped, errors))
    return updated, skipped, errors


def _mark_kodi_unwatched(item):
    """Mark a library item as fully unwatched in Kodi."""
    if item["type"] == "movie":
        _rpc("VideoLibrary.SetMovieDetails", {
            "movieid": item["kodi_id"],
            "playcount": 0,
        })
        logger.debug("sync: movie '{}' marked unwatched".format(item["title"]))

    elif item["type"] == "tvshow":
        result = _rpc("VideoLibrary.GetEpisodes", {
            "tvshowid": item["kodi_id"],
            "properties": ["playcount"],
        })
        if result and "episodes" in result:
            for ep in result["episodes"]:
                if ep.get("playcount", 0) > 0:
                    _rpc("VideoLibrary.SetEpisodeDetails", {
                        "episodeid": ep["episodeid"],
                        "playcount": 0,
                    })
            logger.debug("sync: tvshow '{}' all episodes marked unwatched".format(item["title"]))


def force_sync_from_mal(on_progress=None, is_cancelled=None):
    """
    Force MAL status onto the Kodi library, ignoring local status.
    MAL completed → mark Kodi watched (even if already watched: no-op).
    MAL not completed → mark Kodi unwatched (even if locally watched).

    Returns (updated, skipped, errors).
    """
    items = _get_library_anime()
    total = len(items)
    updated = skipped = errors = 0

    for i, item in enumerate(items):
        if is_cancelled and is_cancelled():
            logger.info("force_sync_from_mal: cancelled by user at item {}/{}".format(i, total))
            break

        if on_progress:
            on_progress(i, total, item["title"])

        mal_status_data = mal_api.get_anime_list_status(item["mal_id"])
        if mal_status_data is None:
            skipped += 1
            continue

        mal_completed = mal_status_data.get("status") == mal_api.STATUS_COMPLETED

        try:
            if mal_completed and not item["watched"]:
                logger.info("force_sync_from_mal: '{}' (mal_id={}) marking Kodi watched".format(
                    item["title"], item["mal_id"]))
                _mark_kodi_watched(item)
                updated += 1
            elif not mal_completed and item["watched"]:
                logger.info("force_sync_from_mal: '{}' (mal_id={}) marking Kodi unwatched".format(
                    item["title"], item["mal_id"]))
                _mark_kodi_unwatched(item)
                updated += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.error("force_sync_from_mal: failed to update '{}': {}".format(item["title"], exc))
            errors += 1

    logger.info("force_sync_from_mal: done — updated={} skipped={} errors={}".format(updated, skipped, errors))
    return updated, skipped, errors
