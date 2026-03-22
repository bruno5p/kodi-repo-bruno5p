"""
Jikan API v4 wrapper.
Base URL: https://api.jikan.moe/v4
Rate limit: 60 requests/minute (1 req/sec safe default).
No authentication required.
"""

import time
import xbmc

try:
    from urllib.request import urlopen, Request
    from urllib.parse import urlencode
    from urllib.error import HTTPError, URLError
except ImportError:
    from urllib2 import urlopen, Request, HTTPError, URLError
    from urllib import urlencode

import json

from resources.lib.logger import logger

BASE_URL = "https://api.jikan.moe/v4"
_last_request_time = 0.0
_MIN_INTERVAL = 1.0  # seconds between requests (safe for 60 req/min)


def _request(path, params=None):
    """Make a GET request to the Jikan API with rate limiting and retry on 429."""
    global _last_request_time

    url = BASE_URL + path
    if params:
        url += "?" + urlencode(params)

    for attempt in range(2):
        # Enforce minimum interval between requests
        elapsed = time.time() - _last_request_time
        if elapsed < _MIN_INTERVAL:
            wait = _MIN_INTERVAL - elapsed
            logger.debug(
                "Rate limiter: waiting {:.2f}s before next request".format(wait)
            )
            time.sleep(wait)

        logger.debug("GET {} (attempt {})".format(url, attempt + 1))
        _last_request_time = time.time()

        try:
            req = Request(
                url, headers={"User-Agent": "metadata.anime.mal/1.0 (Kodi addon)"}
            )
            response = urlopen(req, timeout=10)
            data = json.loads(response.read().decode("utf-8"))
            logger.debug("Response OK for {}".format(url))
            return data
        except HTTPError as e:
            if e.code == 429 and attempt == 0:
                logger.warning(
                    "Rate limited (HTTP 429) for {} — sleeping 2s and retrying".format(
                        url
                    )
                )
                time.sleep(2)
                continue
            if e.code == 404:
                logger.debug("Not found (HTTP 404) for {}".format(url))
                return None
            logger.error("HTTP error {} for {}".format(e.code, url))
            return None
        except URLError as e:
            logger.error("URL error for {}: {}".format(url, str(e)))
            return None

    logger.error("All attempts exhausted for {}".format(url))
    return None


def search(query, anime_type=None):
    """
    Search for anime by title.
    Returns list of anime entries, or empty list on failure.
    """
    logger.debug('search: query="{}" type={}'.format(query, anime_type))
    params = {"q": query, "limit": 25}
    if anime_type:
        params["type"] = anime_type
    data = _request("/anime", params)
    if data and "data" in data:
        results = data["data"]
        logger.debug('search: found {} results for "{}"'.format(len(results), query))
        return results
    logger.debug('search: no results for "{}"'.format(query))
    return []


def get_anime(mal_id):
    """
    Fetch full details for a single anime by MAL ID.
    Returns the anime dict, or None on failure.
    """
    logger.debug("get_anime: mal_id={}".format(mal_id))
    data = _request("/anime/{}".format(mal_id))
    if data and "data" in data:
        anime = data["data"]
        logger.debug(
            'get_anime: retrieved "{}" (type={}, status={})'.format(
                anime.get("title", "?"),
                anime.get("type", "?"),
                anime.get("status", "?"),
            )
        )
        return anime
    logger.debug("get_anime: no data returned for mal_id={}".format(mal_id))
    return None


def get_episodes(mal_id):
    """
    Fetch all episodes for an anime, handling pagination.
    Returns list of episode dicts, or empty list on failure.
    """
    logger.debug("get_episodes: mal_id={}".format(mal_id))
    episodes = []
    page = 1
    while True:
        logger.debug(
            "get_episodes: fetching page {} for mal_id={}".format(page, mal_id)
        )
        data = _request("/anime/{}/episodes".format(mal_id), {"page": page})
        if not data or "data" not in data:
            logger.debug(
                "get_episodes: no data on page {} for mal_id={}".format(page, mal_id)
            )
            break
        page_episodes = data["data"]
        episodes.extend(page_episodes)
        logger.debug(
            "get_episodes: page {} returned {} episodes (total so far: {})".format(
                page, len(page_episodes), len(episodes)
            )
        )
        pagination = data.get("pagination", {})
        if not pagination.get("has_next_page", False):
            break
        page += 1
    logger.debug(
        "get_episodes: fetched {} total episodes for mal_id={}".format(
            len(episodes), mal_id
        )
    )
    return episodes


def get_episode_detail(mal_id, episode_id):
    """
    Fetch detailed info for a single episode.
    Returns the episode dict (may include synopsis, duration), or None on failure.
    """
    logger.debug("get_episode_detail: mal_id={} episode_id={}".format(mal_id, episode_id))
    data = _request("/anime/{}/episodes/{}".format(mal_id, episode_id))
    if data and "data" in data:
        ep = data["data"]
        logger.debug(
            "get_episode_detail: retrieved ep {} \"{}\" synopsis={}".format(
                episode_id,
                ep.get("title", "?"),
                bool(ep.get("synopsis")),
            )
        )
        return ep
    logger.debug("get_episode_detail: no data for mal_id={} episode_id={}".format(mal_id, episode_id))
    return None


def get_pictures(mal_id):
    """
    Fetch all available pictures for an anime.
    Returns list of image dicts (each has 'jpg' and 'webp' keys), or empty list.
    """
    logger.debug("get_pictures: mal_id={}".format(mal_id))
    data = _request("/anime/{}/pictures".format(mal_id))
    if data and "data" in data:
        pictures = data["data"]
        logger.debug(
            "get_pictures: found {} pictures for mal_id={}".format(
                len(pictures), mal_id
            )
        )
        return pictures
    logger.debug("get_pictures: no pictures for mal_id={}".format(mal_id))
    return []


def get_characters(mal_id):
    """
    Fetch character and voice actor info for an anime.
    Returns list of character entries, or empty list.
    """
    logger.debug("get_characters: mal_id={}".format(mal_id))
    data = _request("/anime/{}/characters".format(mal_id))
    if data and "data" in data:
        characters = data["data"]
        logger.debug(
            "get_characters: found {} characters for mal_id={}".format(
                len(characters), mal_id
            )
        )
        return characters
    logger.debug("get_characters: no characters for mal_id={}".format(mal_id))
    return []


def get_relations(mal_id):
    """
    Fetch related anime/manga entries.
    Returns list of relation dicts:
      [{'relation': 'Sequel', 'entry': [{'mal_id': ..., 'type': 'anime', 'name': ...}]}]
    or empty list.
    """
    logger.debug("get_relations: mal_id={}".format(mal_id))
    data = _request("/anime/{}/relations".format(mal_id))
    if data and "data" in data:
        relations = data["data"]
        logger.debug(
            "get_relations: found {} relation groups for mal_id={}".format(
                len(relations), mal_id
            )
        )
        return relations
    logger.debug("get_relations: no relations for mal_id={}".format(mal_id))
    return []
