"""
CRUD operations for lists.json.

lists.json schema — array of one of two shapes:

TMDb Discover list:
{
    "id": 20261030105754,          # int, YYYYMMDDHHmmss timestamp as unique ID
    "type": "tmdb",                # omitted on old entries — treated as "tmdb"
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

Smart Playlist Sampler:
{
    "id": 20261030105754,
    "type": "smartplaylist",
    "label": "My Sampler",
    "description": "",
    "playlist_path": "special://userdata/playlists/video/MyList.xsp",
    "sample_size": 20,
    "sort_by": "random",           # random | title | year | rating | dateadded
    "sort_direction": "ascending"  # ascending | descending (ignored for random)
}

MDBList list:
{
    "id": 20260407123456,
    "type": "mdblist",
    "label": "Top Anime Movies",
    "description": "",
    "mdblist_url": "https://mdblist.com/lists/user/top-anime",
    "total_items": 50,
    "mdblist_filters": {                    # applied only when API key is configured
        "sort": "rank",                     # rank | score | title | imdbrating | mdbrating | released | added
        "order": "asc",                     # asc | desc
        "mediatype": "",                    # "" (all) | "movie" | "show"
        "genres_include": [],               # list of genre name strings; [] = any
        "genres_exclude": [],               # list of genre name strings; [] = none; exclude wins on conflict
        "released_from": "",                # "YYYY-MM-DD" or ""
        "released_to": "",                  # "YYYY-MM-DD" or ""
        "append_to_response": "ratings"     # comma-separated: ratings, reviews, keywords
    },
    "update_interval": 1,         # days between fetches
    "last_updated": null          # ISO date string or null
}

Local + Otaku Recently Watched:
{
    "id": 20261030105754,
    "type": "local_otaku_recent",
    "label": "Recently Watched",
    "description": ""
}

Local + Fen Recently Watched Movies:
{
    "id": 20261030105754,
    "type": "local_fen_recent_movies",
    "label": "Recently Watched Movies",
    "description": ""
}

Local + Fen Recently Watched Series (non-anime):
{
    "id": 20261030105754,
    "type": "local_fen_recent_series",
    "label": "Recently Watched Series",
    "description": ""
}

Note (tmdb): first_air_date_gte and first_air_date_gte_days are mutually exclusive.
      When first_air_date_gte_days is set the actual date is computed at build time.
      For movies "first_air_date_gte" maps to "primary_release_date.gte" in the API.
"""

import json
from datetime import datetime, timedelta

import xbmcvfs

from resources.lib.logger import logger

ADDON_ID = "plugin.list.builder"
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


def add_list(label, description, list_type="tmdb", mediatype=None, update_interval=30,
             filters=None, playlist_config=None, mdblist_config=None, otaku_config=None):
    """
    Create a new list config entry and append it to lists.json.
    Returns the new list entry dict.

    For list_type="tmdb": pass mediatype, update_interval, filters.
    For list_type="smartplaylist": pass playlist_config dict with keys
        playlist_path, sample_size, sort_by, sort_direction.
    """
    list_id = int(datetime.now().strftime("%Y%m%d%H%M%S"))

    if list_type == "smartplaylist":
        entry = {
            "id": list_id,
            "type": "smartplaylist",
            "label": label,
            "description": description,
            "playlist_path": playlist_config["playlist_path"],
            "sample_size": playlist_config["sample_size"],
            "sort_by": playlist_config["sort_by"],
            "sort_direction": playlist_config["sort_direction"],
        }
    elif list_type == "local_otaku_recent":
        entry = {
            "id": list_id,
            "type": "local_otaku_recent",
            "label": label,
            "description": description,
        }
    elif list_type == "local_fen_recent_movies":
        entry = {
            "id": list_id,
            "type": "local_fen_recent_movies",
            "label": label,
            "description": description,
        }
    elif list_type == "local_fen_recent_series":
        entry = {
            "id": list_id,
            "type": "local_fen_recent_series",
            "label": label,
            "description": description,
        }
    elif list_type == "mdblist":
        entry = {
            "id": list_id,
            "type": "mdblist",
            "label": label,
            "description": description,
            "mdblist_url": mdblist_config["mdblist_url"],
            "total_items": mdblist_config.get("total_items", 50),
            "mdblist_filters": mdblist_config.get("mdblist_filters", {
                "sort": "", "order": "", "mediatype": "",
                "genres_include": [], "genres_exclude": [],
                "released_from": "", "released_to": "",
                "append_to_response": "ratings",
            }),
            "update_interval": update_interval,
            "last_updated": None,
        }
    else:
        entry = {
            "id": list_id,
            "type": "tmdb",
            "label": label,
            "description": description,
            "mediatype": mediatype,
            "update_interval": update_interval,
            "last_updated": None,
            "filters": filters or {},
        }

    lists = load_lists()
    lists.append(entry)
    save_lists(lists)
    logger.info("list_manager: added {} list '{}' id={}".format(list_type, label, list_id))
    return entry


def update_list(list_id, updates):
    """
    Merge `updates` dict into the list entry identified by list_id.
    For tmdb entries, a "filters" key in updates is merged into entry["filters"]
    rather than replacing it.
    Raises ValueError if list_id not found.
    """
    lists = load_lists()
    for entry in lists:
        if entry["id"] == list_id:
            filters_update = updates.pop("filters", None)
            entry.update(updates)
            if filters_update is not None and "filters" in entry:
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
    Smartplaylist entries are always dynamic — never need a cache update.
    For tmdb entries: True when last_updated is None or age >= update_interval days.
    """
    if entry.get("type") in ("smartplaylist", "local_otaku_recent", "local_fen_recent_movies", "local_fen_recent_series"):
        return False
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
    Build the widget URL for the given list entry.
    Dynamic types (smartplaylist, otaku_combined) are served directly by this
    plugin; cached types (tmdb, mdblist) are routed through Bingie's
    mdblist_locallist handler.
    """
    if entry.get("type") in ("smartplaylist", "local_otaku_recent", "local_fen_recent_movies", "local_fen_recent_series"):
        return "plugin://plugin.list.builder/?list_id={}".format(entry["id"])
    path = get_items_path(entry["id"])
    return "plugin://plugin.video.tmdb.bingie.helper/?info=mdblist_locallist&&{}".format(path)
