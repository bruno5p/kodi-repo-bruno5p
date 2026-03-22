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
    from urllib.parse import urlencode, quote
    from urllib.error import HTTPError, URLError
except ImportError:
    from urllib2 import urlopen, Request, HTTPError, URLError
    from urllib import urlencode, quote

import json

BASE_URL = 'https://api.jikan.moe/v4'
_last_request_time = 0.0
_MIN_INTERVAL = 1.0  # seconds between requests (safe for 60 req/min)


def _request(path, params=None):
    """Make a GET request to the Jikan API with rate limiting and retry on 429."""
    global _last_request_time

    url = BASE_URL + path
    if params:
        url += '?' + urlencode(params)

    for attempt in range(2):
        # Enforce minimum interval between requests
        elapsed = time.time() - _last_request_time
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)

        xbmc.log('metadata.anime.mal: GET ' + url, xbmc.LOGDEBUG)
        _last_request_time = time.time()

        try:
            req = Request(url, headers={'User-Agent': 'metadata.anime.mal/1.0 (Kodi addon)'})
            response = urlopen(req, timeout=10)
            data = json.loads(response.read().decode('utf-8'))
            return data
        except HTTPError as e:
            if e.code == 429 and attempt == 0:
                xbmc.log('metadata.anime.mal: Rate limited, sleeping 2s', xbmc.LOGWARNING)
                time.sleep(2)
                continue
            if e.code == 404:
                return None
            xbmc.log('metadata.anime.mal: HTTP error {} for {}'.format(e.code, url), xbmc.LOGERROR)
            return None
        except URLError as e:
            xbmc.log('metadata.anime.mal: URL error: {}'.format(str(e)), xbmc.LOGERROR)
            return None

    return None


def search(query, anime_type=None):
    """
    Search for anime by title.
    Returns list of anime entries, or empty list on failure.
    """
    params = {'q': query, 'limit': 25}
    if anime_type:
        params['type'] = anime_type
    data = _request('/anime', params)
    if data and 'data' in data:
        return data['data']
    return []


def get_anime(mal_id):
    """
    Fetch full details for a single anime by MAL ID.
    Returns the anime dict, or None on failure.
    """
    data = _request('/anime/{}'.format(mal_id))
    if data and 'data' in data:
        return data['data']
    return None


def get_episodes(mal_id):
    """
    Fetch all episodes for an anime, handling pagination.
    Returns list of episode dicts, or empty list on failure.
    """
    episodes = []
    page = 1
    while True:
        data = _request('/anime/{}/episodes'.format(mal_id), {'page': page})
        if not data or 'data' not in data:
            break
        episodes.extend(data['data'])
        pagination = data.get('pagination', {})
        if not pagination.get('has_next_page', False):
            break
        page += 1
    return episodes


def get_pictures(mal_id):
    """
    Fetch all available pictures for an anime.
    Returns list of image dicts (each has 'jpg' and 'webp' keys), or empty list.
    """
    data = _request('/anime/{}/pictures'.format(mal_id))
    if data and 'data' in data:
        return data['data']
    return []


def get_characters(mal_id):
    """
    Fetch character and voice actor info for an anime.
    Returns list of character entries, or empty list.
    """
    data = _request('/anime/{}/characters'.format(mal_id))
    if data and 'data' in data:
        return data['data']
    return []


def get_relations(mal_id):
    """
    Fetch related anime/manga entries.
    Returns list of relation dicts:
      [{'relation': 'Sequel', 'entry': [{'mal_id': ..., 'type': 'anime', 'name': ...}]}]
    or empty list.
    """
    data = _request('/anime/{}/relations'.format(mal_id))
    if data and 'data' in data:
        return data['data']
    return []
