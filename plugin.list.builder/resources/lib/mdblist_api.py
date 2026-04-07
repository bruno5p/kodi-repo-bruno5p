"""
MDBList JSON export client.
Fetches items from a public MDBList URL and maps them to the items_list_*.json format.
"""

import requests

from resources.lib.logger import logger


def _normalize_url(url):
    """Convert any MDBList list URL to its /json/ endpoint."""
    clean = url.rstrip("/")
    if not clean.endswith("/json"):
        clean += "/json"
    return clean + "/"


def _map_item(item, rank):
    """
    Map a MDBList export item to the items_list_*.json format.

    MDBList items typically contain: tmdb_id, imdb_id, tvdb_id, mediatype,
    title, rank, year.  poster_path is not provided — Bingie fetches art
    from TMDb when the widget URL is used.
    """
    tmdb_id = item.get("tmdb_id") or item.get("id")
    if not tmdb_id:
        return None

    mediatype = item.get("mediatype") or item.get("type") or "movie"
    if mediatype in ("show", "tvshow", "tv"):
        mediatype = "show"
    else:
        mediatype = "movie"

    return {
        "id": tmdb_id,
        "rank": item.get("rank", rank),
        "adult": 0,
        "title": item.get("title") or item.get("name") or "",
        "imdb_id": item.get("imdb_id"),
        "tvdb_id": item.get("tvdb_id"),
        "language": None,
        "mediatype": mediatype,
        "release_year": item.get("year") or item.get("release_year"),
        "spoken_language": None,
        "poster_path": None,
    }


def get_mdblist_items(url, total_items=None):
    """
    Fetch items from a MDBList URL (public JSON export, no API key needed).

    Accepts both:
    - https://mdblist.com/lists/username/listname
    - https://mdblist.com/lists/username/listname/json/

    Returns a list of item dicts in items_list_*.json format.
    Items without a tmdb_id are silently skipped.
    """
    json_url = _normalize_url(url)
    logger.info("mdblist_api: fetching {}".format(json_url))

    try:
        response = requests.get(json_url, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.error("mdblist_api: request failed: {}".format(e))
        return []

    if isinstance(data, list):
        items_raw = data
    else:
        items_raw = data.get("json") or data.get("items") or []

    items = []
    for i, raw in enumerate(items_raw):
        if total_items and len(items) >= total_items:
            break
        mapped = _map_item(raw, i + 1)
        if mapped:
            items.append(mapped)
        else:
            logger.debug("mdblist_api: skipped item with no tmdb_id at index {}".format(i))

    logger.info("mdblist_api: fetched {} items from {}".format(len(items), json_url))
    return items
