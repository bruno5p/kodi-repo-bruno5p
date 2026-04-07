"""
TMDb Discover API client.
Paginates through results and returns items in the items_list_*.json format.
"""

import re

import requests

from resources.lib.logger import logger

TMDB_BASE_URL = "https://api.themoviedb.org/3"
RESULTS_PER_PAGE = 20  # TMDb always returns 20 results per page
MAX_PAGE = 500          # TMDb hard cap: page 500 * 20 = 10 000 results


def _get_bingie_api_key():
    """
    Read the TMDb API key from Bingie Helper's embedded key file, if installed.
    This is a local fallback so users don't need their own TMDb account.
    Returns the key string, or None if not found.
    """
    try:
        import xbmcvfs
        key_file = xbmcvfs.translatePath(
            "special://home/addons/plugin.video.tmdb.bingie.helper"
            "/resources/tmdbbingiehelper/lib/api/api_keys/tmdb.py"
        )
        with xbmcvfs.File(key_file, "r") as f:
            content = f.read()
        match = re.search(r"API_KEY\s*=\s*'([a-f0-9]{32})'", content)
        if match:
            return match.group(1)
    except Exception as e:
        logger.debug("tmdb_api: could not read Bingie Helper API key: {}".format(e))
    return None


def resolve_api_key(configured_key):
    """
    Return the API key to use: the user-configured key takes priority;
    falls back to Bingie Helper's embedded key.
    Returns (key_string, source_label) or (None, None) if unavailable.
    """
    if configured_key:
        return configured_key, "settings"
    key = _get_bingie_api_key()
    if key:
        return key, "bingie"
    return None, None


def _discover_endpoint(mediatype):
    """Return the discover URL path for 'show' or 'movie'."""
    return "/discover/tv" if mediatype == "show" else "/discover/movie"


def _map_result(result, rank, mediatype):
    """
    Map a single TMDb Discover result dict to the items_list_*.json item format.

    Required by Bingie's ItemMappingBasic:
      id, title, release_year, mediatype

    Additional fields kept for parity with MDbList-scraped items:
      rank, language, adult, imdb_id (None — not in Discover), tvdb_id (None)
    """
    title = result.get("name") or result.get("title") or ""
    date_str = result.get("first_air_date") or result.get("release_date") or ""
    release_year = int(date_str[:4]) if len(date_str) >= 4 and date_str[:4].isdigit() else None

    return {
        "id": result.get("id"),
        "rank": rank,
        "adult": 1 if result.get("adult") else 0,
        "title": title,
        "imdb_id": None,
        "tvdb_id": None,
        "language": result.get("original_language"),
        "mediatype": mediatype,
        "release_year": release_year,
        "spoken_language": result.get("original_language"),
        "poster_path": result.get("poster_path"),
    }


def get_discover_items(mediatype, params, total_items, api_key):
    """
    Fetch up to `total_items` items from the TMDb Discover endpoint.

    Args:
        mediatype:   "show" or "movie"
        params:      dict of TMDb Discover query parameters (without api_key and page)
        total_items: max number of items to return
        api_key:     TMDb v3 API key string (may be empty — will try Bingie fallback)

    Returns:
        list of item dicts in items_list_*.json format, length <= total_items.
        Returns [] on complete failure (errors are logged).
    """
    key, source = resolve_api_key(api_key)
    if not key:
        logger.error("tmdb_api: no API key available (configure one in addon settings, or install Bingie Helper)")
        return []

    if source == "bingie":
        logger.debug("tmdb_api: using Bingie Helper API key as fallback")

    endpoint = TMDB_BASE_URL + _discover_endpoint(mediatype)
    items = []
    pages_needed = -(-total_items // RESULTS_PER_PAGE)  # ceiling division without math import
    pages_needed = min(pages_needed, MAX_PAGE)

    for page in range(1, pages_needed + 1):
        request_params = dict(params)
        request_params["api_key"] = key
        request_params["page"] = page

        try:
            response = requests.get(endpoint, params=request_params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error("tmdb_api: request failed page={} error={}".format(page, e))
            break  # return whatever we have so far

        results = data.get("results", [])
        total_pages_available = data.get("total_pages", 1)

        if not results:
            logger.debug("tmdb_api: no results on page {}".format(page))
            break

        for result in results:
            rank = len(items) + 1
            items.append(_map_result(result, rank, mediatype))
            if len(items) >= total_items:
                break

        logger.debug("tmdb_api: fetched page {}/{} total_so_far={}".format(
            page, min(pages_needed, total_pages_available), len(items)
        ))

        if page >= total_pages_available or len(items) >= total_items:
            break

    logger.info("tmdb_api: fetched {} items for mediatype={}".format(len(items), mediatype))
    return items
