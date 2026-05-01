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

        mal_status_data = mal_api.get_anime_list_status(item["mal_id"])
        if mal_status_data is None:
            skipped += 1
            continue

        mal_status = mal_status_data.get("status")
        mal_watched_ep = mal_status_data.get("num_episodes_watched", 0) or 0

        logger.info("sync_from_mal: '{}' (mal_id={}) type={} mal_status={} mal_ep={} kodi_ep={} kodi_watched={}".format(
            item["title"], item["mal_id"], item["type"],
            mal_status, mal_watched_ep, item["watched_episodes"], item["watched"]))

        if mal_status == mal_api.STATUS_COMPLETED and not item["watched"]:
            logger.info("sync_from_mal: '{}' (mal_id={}) completed on MAL, updating Kodi".format(
                item["title"], item["mal_id"]))
            try:
                _mark_kodi_watched(item)
                updated += 1
            except Exception as exc:
                logger.error("sync_from_mal: failed to update '{}': {}".format(item["title"], exc))
                errors += 1
        elif (mal_status == mal_api.STATUS_WATCHING
              and item["type"] == "tvshow"
              and mal_watched_ep > item["watched_episodes"]):
            logger.info("sync_from_mal: '{}' (mal_id={}) watching on MAL ({} ep), Kodi has {}, updating".format(
                item["title"], item["mal_id"], mal_watched_ep, item["watched_episodes"]))
            try:
                _mark_kodi_episodes_watched(item, mal_watched_ep)
                updated += 1
            except Exception as exc:
                logger.error("sync_from_mal: failed to update '{}': {}".format(item["title"], exc))
                errors += 1
        else:
            logger.info("sync_from_mal: '{}' skipped (no condition matched)".format(item["title"]))
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

        kodi_watched_ep = item["watched_episodes"]

        if kodi_watched_ep == 0:
            # Nothing watched locally — nothing to push
            skipped += 1
            continue

        mal_status_data = mal_api.get_anime_list_status(item["mal_id"])
        mal_status = mal_status_data.get("status") if mal_status_data else None
        mal_watched_ep = (mal_status_data.get("num_episodes_watched", 0) or 0) if mal_status_data else 0

        if item["watched"]:
            # All episodes watched — push completed
            if mal_status == mal_api.STATUS_COMPLETED:
                skipped += 1
                continue
            logger.info("sync_to_mal: '{}' (mal_id={}) fully watched, updating MAL to completed".format(
                item["title"], item["mal_id"]))
            result = mal_api.update_anime_status(item["mal_id"], status=mal_api.STATUS_COMPLETED)
            if result:
                updated += 1
            else:
                logger.error("sync_to_mal: failed to update '{}' on MAL".format(item["title"]))
                errors += 1
        elif item["type"] == "tvshow" and kodi_watched_ep > mal_watched_ep:
            # Partially watched — push episode count as watching
            logger.info("sync_to_mal: '{}' (mal_id={}) partial Kodi={} MAL={}, updating MAL watching".format(
                item["title"], item["mal_id"], kodi_watched_ep, mal_watched_ep))
            result = mal_api.update_anime_status(
                item["mal_id"],
                status=mal_api.STATUS_WATCHING,
                num_watched=kodi_watched_ep,
            )
            if result:
                updated += 1
            else:
                logger.error("sync_to_mal: failed to update '{}' on MAL".format(item["title"]))
                errors += 1
        else:
            skipped += 1

    logger.info("sync_to_mal: done — updated={} skipped={} errors={}".format(updated, skipped, errors))
    return updated, skipped, errors


def _mark_kodi_episodes_watched(item, n):
    """
    Mark exactly the first *n* regular episodes (season > 0, sorted by season
    then episode number) as watched, and all others as unwatched.
    Specials (season 0) are left untouched.
    """
    result = _rpc("VideoLibrary.GetEpisodes", {
        "tvshowid": item["kodi_id"],
        "properties": ["season", "episode", "playcount"],
    })
    if not result or "episodes" not in result:
        return

    regular = sorted(
        [e for e in result["episodes"] if e.get("season", 0) > 0],
        key=lambda e: (e.get("season", 0), e.get("episode", 0)),
    )

    watched_ids = {e["episodeid"] for e in regular[:n]}

    for ep in regular:
        target = 1 if ep["episodeid"] in watched_ids else 0
        if ep.get("playcount", 0) != target:
            _rpc("VideoLibrary.SetEpisodeDetails", {
                "episodeid": ep["episodeid"],
                "playcount": target,
            })

    logger.debug("sync: tvshow '{}' first {}/{} episodes marked watched".format(
        item["title"], n, len(regular)))


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

        mal_status = mal_status_data.get("status")
        mal_watched_ep = mal_status_data.get("num_episodes_watched", 0) or 0

        try:
            if mal_status == mal_api.STATUS_COMPLETED:
                if not item["watched"]:
                    logger.info("force_sync_from_mal: '{}' (mal_id={}) marking Kodi watched".format(
                        item["title"], item["mal_id"]))
                    _mark_kodi_watched(item)
                    updated += 1
                else:
                    skipped += 1
            elif (mal_status == mal_api.STATUS_WATCHING
                  and item["type"] == "tvshow"
                  and mal_watched_ep != item["watched_episodes"]):
                logger.info("force_sync_from_mal: '{}' (mal_id={}) setting Kodi to {} ep watched".format(
                    item["title"], item["mal_id"], mal_watched_ep))
                _mark_kodi_episodes_watched(item, mal_watched_ep)
                updated += 1
            elif mal_status not in (mal_api.STATUS_COMPLETED, mal_api.STATUS_WATCHING) and item["watched"]:
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


# ── Single-item sync ──────────────────────────────────────────────────────────

def sync_single_from_mal(mal_id):
    """Update from MAL for one item (MAL → Kodi, keep higher local)."""
    items = [i for i in _get_library_anime() if i["mal_id"] == mal_id]
    if not items:
        return 0, 0, 0
    updated = skipped = errors = 0
    for item in items:
        mal_status_data = mal_api.get_anime_list_status(item["mal_id"])
        if mal_status_data is None:
            skipped += 1
            continue
        mal_status = mal_status_data.get("status")
        mal_watched_ep = mal_status_data.get("num_episodes_watched", 0) or 0
        try:
            if mal_status == mal_api.STATUS_COMPLETED and not item["watched"]:
                logger.info("sync_single_from_mal: '{}' completed on MAL, updating Kodi".format(item["title"]))
                _mark_kodi_watched(item)
                updated += 1
            elif (mal_status == mal_api.STATUS_WATCHING
                  and item["type"] == "tvshow"
                  and mal_watched_ep > item["watched_episodes"]):
                logger.info("sync_single_from_mal: '{}' watching on MAL ({} ep), updating Kodi".format(
                    item["title"], mal_watched_ep))
                _mark_kodi_episodes_watched(item, mal_watched_ep)
                updated += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.error("sync_single_from_mal: failed to update '{}': {}".format(item["title"], exc))
            errors += 1
    logger.info("sync_single_from_mal: mal_id={} — updated={} skipped={} errors={}".format(
        mal_id, updated, skipped, errors))
    return updated, skipped, errors


def sync_single_to_mal(mal_id):
    """Update to MAL for one item (Kodi → MAL, keep higher MAL)."""
    items = [i for i in _get_library_anime() if i["mal_id"] == mal_id]
    if not items:
        return 0, 0, 0
    updated = skipped = errors = 0
    for item in items:
        kodi_watched_ep = item["watched_episodes"]
        if kodi_watched_ep == 0:
            skipped += 1
            continue
        mal_status_data = mal_api.get_anime_list_status(item["mal_id"])
        mal_status = mal_status_data.get("status") if mal_status_data else None
        mal_watched_ep = (mal_status_data.get("num_episodes_watched", 0) or 0) if mal_status_data else 0
        try:
            if item["watched"]:
                if mal_status == mal_api.STATUS_COMPLETED:
                    skipped += 1
                    continue
                logger.info("sync_single_to_mal: '{}' fully watched, updating MAL to completed".format(item["title"]))
                result = mal_api.update_anime_status(item["mal_id"], status=mal_api.STATUS_COMPLETED)
                if result:
                    updated += 1
                else:
                    logger.error("sync_single_to_mal: failed to update '{}' on MAL".format(item["title"]))
                    errors += 1
            elif item["type"] == "tvshow" and kodi_watched_ep > mal_watched_ep:
                logger.info("sync_single_to_mal: '{}' partial Kodi={} MAL={}, updating MAL".format(
                    item["title"], kodi_watched_ep, mal_watched_ep))
                result = mal_api.update_anime_status(
                    item["mal_id"],
                    status=mal_api.STATUS_WATCHING,
                    num_watched=kodi_watched_ep,
                )
                if result:
                    updated += 1
                else:
                    logger.error("sync_single_to_mal: failed to update '{}' on MAL".format(item["title"]))
                    errors += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.error("sync_single_to_mal: failed for '{}': {}".format(item["title"], exc))
            errors += 1
    logger.info("sync_single_to_mal: mal_id={} — updated={} skipped={} errors={}".format(
        mal_id, updated, skipped, errors))
    return updated, skipped, errors


def force_sync_single_from_mal(mal_id):
    """Reset to MAL status for one item (force MAL status onto Kodi)."""
    items = [i for i in _get_library_anime() if i["mal_id"] == mal_id]
    if not items:
        return 0, 0, 0
    updated = skipped = errors = 0
    for item in items:
        mal_status_data = mal_api.get_anime_list_status(item["mal_id"])
        if mal_status_data is None:
            skipped += 1
            continue
        mal_status = mal_status_data.get("status")
        mal_watched_ep = mal_status_data.get("num_episodes_watched", 0) or 0
        try:
            if mal_status == mal_api.STATUS_COMPLETED:
                if not item["watched"]:
                    logger.info("force_sync_single_from_mal: '{}' marking Kodi watched".format(item["title"]))
                    _mark_kodi_watched(item)
                    updated += 1
                else:
                    skipped += 1
            elif (mal_status == mal_api.STATUS_WATCHING
                  and item["type"] == "tvshow"
                  and mal_watched_ep != item["watched_episodes"]):
                logger.info("force_sync_single_from_mal: '{}' setting Kodi to {} ep watched".format(
                    item["title"], mal_watched_ep))
                _mark_kodi_episodes_watched(item, mal_watched_ep)
                updated += 1
            elif mal_status not in (mal_api.STATUS_COMPLETED, mal_api.STATUS_WATCHING) and item["watched"]:
                logger.info("force_sync_single_from_mal: '{}' marking Kodi unwatched".format(item["title"]))
                _mark_kodi_unwatched(item)
                updated += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.error("force_sync_single_from_mal: failed for '{}': {}".format(item["title"], exc))
            errors += 1
    logger.info("force_sync_single_from_mal: mal_id={} — updated={} skipped={} errors={}".format(
        mal_id, updated, skipped, errors))
    return updated, skipped, errors
