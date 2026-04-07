"""
Builds items JSON files from TMDb Discover API responses.
Translates list config filters into TMDb API parameters.
"""

import json
from datetime import datetime, timedelta

import xbmcvfs

from resources.lib.logger import logger
from resources.lib.tmdb_api import get_discover_items

ADDON_ID = "plugin.list.builder"

# Date field names differ between TV and movie in the TMDb Discover API
_TV_DATE_FIELD = "first_air_date"
_MOVIE_DATE_FIELD = "primary_release_date"


def build_discover_params(entry):
    """
    Convert a list config entry's filters dict to TMDb Discover API query params.

    Returns a dict ready to pass as `params` to get_discover_items()
    (excludes api_key and page — those are added by tmdb_api).
    """
    filters = entry.get("filters", {})
    mediatype = entry.get("mediatype", "show")
    date_field = _TV_DATE_FIELD if mediatype == "show" else _MOVIE_DATE_FIELD

    params = {}

    lang = filters.get("with_original_language")
    if lang:
        params["with_original_language"] = lang

    country = filters.get("with_origin_country")
    if country:
        params["with_origin_country"] = country

    # TMDb expects comma-separated genre IDs (comma = AND logic)
    with_genres = filters.get("with_genres")
    if with_genres:
        params["with_genres"] = ",".join(str(g) for g in with_genres)

    without_genres = filters.get("without_genres")
    if without_genres:
        params["without_genres"] = ",".join(str(g) for g in without_genres)

    sort_by = filters.get("sort_by")
    if sort_by:
        params["sort_by"] = sort_by

    # Static date takes priority over dynamic days-ago
    static_date = filters.get("first_air_date_gte")
    days_ago = filters.get("first_air_date_gte_days")
    if static_date:
        params["{}.gte".format(date_field)] = static_date
    elif days_ago is not None:
        cutoff = datetime.now() - timedelta(days=int(days_ago))
        params["{}.gte".format(date_field)] = cutoff.strftime("%Y-%m-%d")

    vote_count_gte = filters.get("vote_count_gte")
    if vote_count_gte is not None:
        params["vote_count.gte"] = int(vote_count_gte)

    vote_average_gte = filters.get("vote_average_gte")
    if vote_average_gte is not None:
        params["vote_average.gte"] = float(vote_average_gte)
        if not vote_count_gte:
            logger.warning("list_builder: vote_average_gte set without vote_count_gte — results may be noisy")

    vote_average_lte = filters.get("vote_average_lte")
    if vote_average_lte is not None:
        params["vote_average.lte"] = float(vote_average_lte)

    return params


def build_mdblist_list(entry):
    """
    Fetch items from a MDBList URL and write items_list_{id}.json.

    Args:
        entry: list config dict with keys: id, label, mdblist_url, total_items

    Returns:
        True on success, False on failure.
    """
    from resources.lib.mdblist_api import get_mdblist_items

    list_id = entry["id"]
    label = entry.get("label", str(list_id))
    url = entry.get("mdblist_url", "")
    total_items = entry.get("total_items", 50)

    logger.info("list_builder: building mdblist '{}' id={}".format(label, list_id))

    items = get_mdblist_items(url, total_items)

    if not items:
        logger.warning("list_builder: got 0 items for mdblist id={}".format(list_id))

    output_path = xbmcvfs.translatePath(
        "special://profile/addon_data/{}/lists/items_list_{}.json".format(ADDON_ID, list_id)
    )

    try:
        with xbmcvfs.File(output_path, "w") as f:
            f.write(json.dumps(items, indent=4))
        logger.info("list_builder: wrote {} items to {}".format(len(items), output_path))
        return True
    except IOError as e:
        logger.error("list_builder: failed to write items file: {}".format(e))
        return False


def build_entry(entry, api_key=None):
    """
    Dispatcher: build any cacheable entry type.
    - "mdblist":  calls build_mdblist_list(entry) — no api_key needed
    - "tmdb" / default: calls build_list(entry, api_key)
    Smartplaylist entries are always dynamic and should never reach this function.
    """
    if entry.get("type") == "mdblist":
        return build_mdblist_list(entry)
    return build_list(entry, api_key or "")


def build_list(entry, api_key):
    """
    Fetch items from TMDb Discover API and write items_list_{id}.json.

    Args:
        entry:   list config dict (from lists.json)
        api_key: TMDb v3 API key string

    Returns:
        True on success, False on failure.
    """
    list_id = entry["id"]
    mediatype = entry.get("mediatype", "show")
    total_items = entry.get("filters", {}).get("total_items", 50)
    label = entry.get("label", str(list_id))

    logger.info("list_builder: building list '{}' id={}".format(label, list_id))

    params = build_discover_params(entry)
    logger.debug("list_builder: discover params={}".format(params))

    items = get_discover_items(
        mediatype=mediatype,
        params=params,
        total_items=total_items,
        api_key=api_key,
    )

    if not items:
        logger.warning("list_builder: got 0 items for list id={}".format(list_id))

    output_path = xbmcvfs.translatePath(
        "special://profile/addon_data/{}/lists/items_list_{}.json".format(ADDON_ID, list_id)
    )

    try:
        with xbmcvfs.File(output_path, "w") as f:
            f.write(json.dumps(items, indent=4))
        logger.info("list_builder: wrote {} items to {}".format(len(items), output_path))
        return True
    except IOError as e:
        logger.error("list_builder: failed to write items file: {}".format(e))
        return False
