"""
Helpers for reading Kodi smart playlists (.xsp files).

list_smartplaylists() — discover available video smart playlists.
get_playlist_items()  — fetch a sample of items from a smart playlist.

Strategy: parse the .xsp XML to extract media type + filter rules, then call
VideoLibrary.GetTVShows / VideoLibrary.GetMovies directly.  This is more
reliable than Files.GetDirectory, which does not evaluate .xsp rule files in
all Kodi configurations.
"""

import io
import json
import random as _random
import xml.etree.ElementTree as ET

import xbmc
import xbmcvfs

from resources.lib.logger import logger

PLAYLISTS_DIR = "special://userdata/playlists/video/"

SAMPLER_SORT_OPTIONS = [
    ("Random",     "random"),
    ("Title",      "title"),
    ("Year",       "year"),
    ("Rating",     "rating"),
    ("Date Added", "dateadded"),
]


def list_smartplaylists():
    """
    Return a list of (display_name, full_path) for all .xsp files in the
    user's video playlists directory.  display_name is the filename without extension.
    Returns [] if the directory is missing or empty.
    """
    dir_path = xbmcvfs.translatePath(PLAYLISTS_DIR)
    if not xbmcvfs.exists(dir_path):
        logger.debug("smartplaylist_reader: playlists directory not found")
        return []

    try:
        _, files = xbmcvfs.listdir(dir_path)
    except Exception as e:
        logger.error("smartplaylist_reader: failed to list playlists dir: {}".format(e))
        return []

    result = []
    for fname in sorted(files):
        if fname.lower().endswith(".xsp"):
            display = fname[:-4]  # strip .xsp
            full_path = PLAYLISTS_DIR + fname
            result.append((display, full_path))

    logger.debug("smartplaylist_reader: found {} smart playlists".format(len(result)))
    return result


def _parse_xsp(playlist_path):
    """
    Read and parse a .xsp smart playlist file.

    Returns (media_type, kodi_filter) where:
      - media_type: "movies" | "tvshows" | "episodes" | ...
      - kodi_filter: dict compatible with VideoLibrary filter param, or None
    """
    translated = xbmcvfs.translatePath(playlist_path)
    try:
        with io.open(translated, "r", encoding="utf-8") as f:
            content = f.read()
        root = ET.fromstring(content)
    except Exception as e:
        logger.error("smartplaylist_reader: failed to parse '{}': {}".format(playlist_path, e))
        return None, None

    media_type = root.get("type", "")  # "movies", "tvshows", "episodes", ...
    match = root.findtext("match", "all")  # "all"=AND, "any"=OR

    rules = []
    for rule_el in root.findall("rule"):
        field = rule_el.get("field", "")
        operator = rule_el.get("operator", "contains")
        values = [v.text for v in rule_el.findall("value") if v.text]
        if not field or not values:
            continue
        for value in values:
            rules.append({"field": field, "operator": operator, "value": value})

    if not rules:
        kodi_filter = None
    elif len(rules) == 1:
        kodi_filter = rules[0]
    else:
        connector = "and" if match == "all" else "or"
        kodi_filter = {connector: rules}

    logger.debug("smartplaylist_reader: parsed xsp type='{}' rules={}".format(media_type, len(rules)))
    return media_type, kodi_filter


def _rpc(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        raw = xbmc.executeJSONRPC(json.dumps(payload))
        response = json.loads(raw)
    except Exception as e:
        logger.error("smartplaylist_reader: JSON-RPC exception: {}".format(e))
        return None
    if "error" in response:
        logger.error("smartplaylist_reader: JSON-RPC error {}: {}".format(method, response["error"]))
        return None
    return response.get("result")


def get_playlist_items(playlist_path, sample_size, sort_by, sort_direction):
    """
    Fetch up to sample_size items from the smart playlist at playlist_path.

    Parses the .xsp XML to get media type and filter rules, then calls the
    appropriate VideoLibrary method.  Sort and limit are applied in Python.

    Returns a list of dicts:
        {
            "title":     str,
            "mediatype": str,       # "movie" | "tvshow"
            "file":      str,       # playable URL or videodb:// directory URL
            "year":      int|None,
            "art":       dict,
            "rating":    float|None,
            "dateadded": str|None,
            "is_folder": bool,      # True for tvshows (directory items)
        }
    """
    media_type, kodi_filter = _parse_xsp(playlist_path)
    if not media_type:
        return []

    if media_type in ("movies", "movie"):
        method = "VideoLibrary.GetMovies"
        result_key = "movies"
        item_type = "movie"
        properties = ["title", "year", "art", "rating", "dateadded", "file"]
    elif media_type in ("tvshows", "tvshow"):
        method = "VideoLibrary.GetTVShows"
        result_key = "tvshows"
        item_type = "tvshow"
        properties = ["title", "year", "art", "rating", "dateadded"]
    else:
        logger.warning("smartplaylist_reader: unsupported playlist type '{}'".format(media_type))
        return []

    params = {"properties": properties}
    if kodi_filter:
        params["filter"] = kodi_filter

    result = _rpc(method, params)
    if result is None:
        return []

    entries = result.get(result_key) or []
    logger.debug("smartplaylist_reader: {} entries from {} ({})".format(
        len(entries), playlist_path, media_type))

    items = []
    for e in entries:
        if item_type == "tvshow":
            show_id = e.get("tvshowid", "")
            file_url = "videodb://tvshows/titles/{}/".format(show_id)
            is_folder = True
        else:
            file_url = e.get("file", "")
            is_folder = False

        items.append({
            "title":     e.get("label") or e.get("title") or "",
            "mediatype": item_type,
            "file":      file_url,
            "year":      e.get("year") or None,
            "art":       e.get("art") or {},
            "rating":    e.get("rating") or None,
            "dateadded": e.get("dateadded") or None,
            "is_folder": is_folder,
        })

    # Sort in Python
    if sort_by == "random":
        _random.shuffle(items)
    elif sort_by == "title":
        items.sort(key=lambda x: x.get("title", "").lower(),
                   reverse=(sort_direction == "descending"))
    elif sort_by == "year":
        items.sort(key=lambda x: x.get("year") or 0,
                   reverse=(sort_direction == "descending"))
    elif sort_by == "rating":
        items.sort(key=lambda x: x.get("rating") or 0,
                   reverse=(sort_direction == "descending"))
    elif sort_by == "dateadded":
        items.sort(key=lambda x: x.get("dateadded") or "",
                   reverse=(sort_direction == "descending"))

    return items[:sample_size]
