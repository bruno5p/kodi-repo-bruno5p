"""
CRUD operations for lists.json.

lists.json schema — array of:
{
    "id": 20261030105754,          # int, YYYYMMDDHHmmss timestamp as unique ID
    "label": "Top Rated TV Dorama",
    "description": "...",
    "mediatype": "show",           # "show" | "movie"
    "update_interval": 30,         # days between updates
    "last_updated": "2026-03-31",  # ISO date string or null
    "filters": {
        "with_original_language": "ja",          # ISO 639-1 or null
        "with_origin_country": "JP",             # ISO 3166-1 upper or null
        "with_genres": [18, 9648],               # list of ints or []
        "without_genres": [16],                  # list of ints or []
        "sort_by": "vote_count.desc",
        "first_air_date_gte": "1991-01-01",      # static date string or null
        "first_air_date_gte_days": null,         # int days-ago (dynamic) or null
        "vote_count_gte": 100,                   # int or null
        "vote_average_gte": null,                # float or null
        "vote_average_lte": null,                # float or null
        "total_items": 80                        # total items to fetch
    }
}

Note: first_air_date_gte and first_air_date_gte_days are mutually exclusive.
      When first_air_date_gte_days is set the actual date is computed at build time.
      For movies "first_air_date_gte" maps to "primary_release_date.gte" in the API.
"""

import json
from datetime import datetime, timedelta

import xbmcvfs

from resources.lib.logger import logger

ADDON_ID = "script.tmdb.lists"
LISTS_PATH = "special://profile/addon_data/{}/lists.json".format(ADDON_ID)
LISTS_DIR = "special://profile/addon_data/{}/lists/".format(ADDON_ID)
DATA_DIR = "special://profile/addon_data/{}/".format(ADDON_ID)


def _ensure_data_dir():
    """Create addon_data directory and lists/ subdirectory if they don't exist."""
    data_dir = xbmcvfs.translatePath(DATA_DIR)
    lists_dir = xbmcvfs.translatePath(LISTS_DIR)
    if not xbmcvfs.exists(data_dir):
        xbmcvfs.mkdirs(data_dir)
    if not xbmcvfs.exists(lists_dir):
        xbmcvfs.mkdirs(lists_dir)


def load_lists():
    """Load and return the list of list configs. Returns [] if file missing or invalid."""
    path = xbmcvfs.translatePath(LISTS_PATH)
    if not xbmcvfs.exists(path):
        logger.debug("list_manager: lists.json not found, returning empty list")
        return []
    try:
        with xbmcvfs.File(path, "r") as f:
            return json.load(f)
    except (IOError, ValueError) as e:
        logger.error("list_manager: failed to load lists.json: {}".format(e))
        return []


def save_lists(lists):
    """Persist the list of list configs to lists.json."""
    _ensure_data_dir()
    path = xbmcvfs.translatePath(LISTS_PATH)
    try:
        with xbmcvfs.File(path, "w") as f:
            f.write(json.dumps(lists, indent=4))
        logger.debug("list_manager: saved {} lists to lists.json".format(len(lists)))
    except IOError as e:
        logger.error("list_manager: failed to save lists.json: {}".format(e))
        raise


def add_list(label, description, mediatype, update_interval, filters):
    """
    Create a new list config entry and append it to lists.json.
    Returns the new list entry dict.
    """
    list_id = int(datetime.now().strftime("%Y%m%d%H%M%S"))
    entry = {
        "id": list_id,
        "label": label,
        "description": description,
        "mediatype": mediatype,
        "update_interval": update_interval,
        "last_updated": None,
        "filters": filters,
    }
    lists = load_lists()
    lists.append(entry)
    save_lists(lists)
    logger.info("list_manager: added list '{}' id={}".format(label, list_id))
    return entry


def update_list(list_id, updates):
    """
    Merge `updates` dict into the list entry identified by list_id.
    A "filters" key in updates is merged into entry["filters"] rather than replacing it.
    Raises ValueError if list_id not found.
    """
    lists = load_lists()
    for entry in lists:
        if entry["id"] == list_id:
            filters_update = updates.pop("filters", None)
            entry.update(updates)
            if filters_update is not None:
                entry["filters"].update(filters_update)
            save_lists(lists)
            logger.info("list_manager: updated list id={}".format(list_id))
            return entry
    raise ValueError("list_manager: list_id {} not found".format(list_id))


def delete_list(list_id):
    """
    Remove the list config from lists.json and delete its items file if present.
    Returns True if found and deleted, False otherwise.
    """
    lists = load_lists()
    new_lists = [e for e in lists if e["id"] != list_id]
    if len(new_lists) == len(lists):
        logger.warning("list_manager: delete_list called with unknown id={}".format(list_id))
        return False

    save_lists(new_lists)

    items_path = xbmcvfs.translatePath(get_items_path(list_id))
    if xbmcvfs.exists(items_path):
        xbmcvfs.delete(items_path)
        logger.info("list_manager: deleted items file for id={}".format(list_id))

    logger.info("list_manager: deleted list id={}".format(list_id))
    return True


def mark_updated(list_id):
    """Set last_updated to today's date string for the given list_id."""
    today = datetime.now().strftime("%Y-%m-%d")
    update_list(list_id, {"last_updated": today})


def needs_update(entry):
    """
    Return True if the list should be refreshed.
    True when: last_updated is None, or today >= last_updated + update_interval days.
    """
    last_updated = entry.get("last_updated")
    if last_updated is None:
        return True
    try:
        last_dt = datetime.strptime(last_updated, "%Y-%m-%d")
    except ValueError:
        return True
    interval = entry.get("update_interval", 30)
    return datetime.now() >= last_dt + timedelta(days=interval)


def get_items_path(list_id):
    """Return the special:// path for the items JSON file of the given list."""
    return "special://profile/addon_data/{}/lists/items_list_{}.json".format(ADDON_ID, list_id)


def get_widget_url(entry):
    """
    Build the Bingie mdblist_locallist plugin URL for the given list entry.
    The &&-separated second segment is the special:// path.
    Bingie's router does unquote_plus() on each secondary param so plain
    special:// paths round-trip correctly without encoding.
    """
    path = get_items_path(entry["id"])
    return "plugin://plugin.video.tmdb.bingie.helper/?info=mdblist_locallist&&{}".format(path)
