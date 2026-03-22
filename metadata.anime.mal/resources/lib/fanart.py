"""
Fanart.tv API v3 wrapper for anime artwork.

ID mapping chain:
  MAL ID -> AniDB ID (via Jikan /external)
         -> TheTVDB ID (via cached Anime-Lists XML)
         -> Fanart.tv artwork

Requires a free Fanart.tv API key (register at fanart.tv).
"""

import json
import os
import time

import xbmc
import xbmcvfs

try:
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError, URLError
    from xml.etree import cElementTree as ET
except ImportError:
    from urllib2 import urlopen, Request, HTTPError, URLError
    from xml.etree import ElementTree as ET

from resources.lib.logger import logger

FANART_BASE = "https://webservice.fanart.tv/v3"
ANIMELIST_URL = (
    "https://raw.githubusercontent.com/Anime-Lists/anime-lists/master/anime-list.xml"
)
_ANIMELIST_CACHE_TTL = 7 * 24 * 3600  # 7 days in seconds

_animelist_root = None  # in-memory cache of parsed XML root


def _cache_path():
    profile = xbmcvfs.translatePath("special://userdata/addon_data/metadata.anime.mal/")
    return os.path.join(profile, "anime-list.xml")


def _load_animelist():
    """Return parsed XML root of anime-list.xml, downloading/caching as needed."""
    global _animelist_root
    if _animelist_root is not None:
        return _animelist_root

    path = _cache_path()
    xml_bytes = None

    # Try reading from disk cache
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < _ANIMELIST_CACHE_TTL:
            logger.debug(
                "fanart: reading anime-list.xml from cache (age={:.0f}s)".format(age)
            )
            try:
                with open(path, "rb") as f:
                    xml_bytes = f.read()
            except IOError as e:
                logger.warning(
                    "fanart: could not read cached anime-list.xml: {}".format(e)
                )

    # Download if cache is missing or stale
    if xml_bytes is None:
        logger.debug("fanart: downloading anime-list.xml from Anime-Lists")
        try:
            req = Request(
                ANIMELIST_URL,
                headers={"User-Agent": "metadata.anime.mal/1.0 (Kodi addon)"},
            )
            response = urlopen(req, timeout=20)
            xml_bytes = response.read()
            # Write to cache
            cache_dir = os.path.dirname(path)
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            with open(path, "wb") as f:
                f.write(xml_bytes)
            logger.debug(
                "fanart: cached anime-list.xml ({} bytes)".format(len(xml_bytes))
            )
        except (HTTPError, URLError, IOError) as e:
            logger.error("fanart: failed to download anime-list.xml: {}".format(e))
            # Fall back to stale cache if available
            if os.path.exists(path):
                logger.warning("fanart: using stale anime-list.xml cache as fallback")
                try:
                    with open(path, "rb") as f:
                        xml_bytes = f.read()
                except IOError:
                    pass

    if xml_bytes is None:
        logger.error("fanart: anime-list.xml unavailable")
        return None

    try:
        _animelist_root = ET.fromstring(xml_bytes)
        return _animelist_root
    except ET.ParseError as e:
        logger.error("fanart: failed to parse anime-list.xml: {}".format(e))
        return None


def anidb_to_thetvdb(anidb_id):
    """
    Map an AniDB ID to a TheTVDB ID using the Anime-Lists XML.
    Returns TheTVDB ID string, or None if not found / unmapped.
    """
    root = _load_animelist()
    if root is None:
        return None

    target = str(anidb_id)
    for elem in root.iter("anime"):
        if elem.get("anidbid") == target:
            tvdbid = elem.get("tvdbid", "")
            if tvdbid and tvdbid not in ("", "unknown", "0"):
                logger.debug(
                    "fanart: anidb_id={} -> thetvdb_id={}".format(anidb_id, tvdbid)
                )
                return tvdbid
            break  # found entry but no valid tvdbid

    logger.debug("fanart: no TheTVDB mapping for anidb_id={}".format(anidb_id))
    return None


def get_artwork(thetvdb_id, api_key, lang_pref="en"):
    """
    Fetch Fanart.tv artwork for a TV show by TheTVDB ID.

    lang_pref: 'en' or 'ja' — preferred language for clearlogo selection.

    Returns dict mapping Kodi art type -> list of URLs:
      fanart, landscape, banner, clearlogo, clearart
    """
    if not thetvdb_id or not api_key:
        return {}

    url = "{}/tv/{}".format(FANART_BASE, thetvdb_id)
    logger.debug("fanart: GET {}".format(url))

    try:
        req = Request(
            url,
            headers={
                "User-Agent": "metadata.anime.mal/1.0 (Kodi addon)",
                "api-key": api_key,
            },
        )
        response = urlopen(req, timeout=10)
        res = json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        logger.error("fanart: HTTP {} for {}".format(e.code, url))
        return {}
    except URLError as e:
        logger.error("fanart: URL error for {}: {}".format(url, e))
        return {}

    accepted_langs = {lang_pref, "en", "ja", ""}

    def pick_urls(key):
        return [
            i["url"]
            for i in (res.get(key) or [])
            if i.get("lang", "") in accepted_langs and i.get("url")
        ]

    art = {}

    if res.get("showbackground"):
        urls = pick_urls("showbackground")
        if urls:
            art["fanart"] = urls

    if res.get("tvthumb"):
        urls = pick_urls("tvthumb")
        if urls:
            art["landscape"] = urls

    if res.get("tvbanner"):
        urls = pick_urls("tvbanner")
        if urls:
            art["banner"] = urls

    # clearlogo: prefer lang_pref, fall back to any accepted language
    for logo_key in ("clearlogo", "hdtvlogo"):
        candidates = [
            i
            for i in (res.get(logo_key) or [])
            if i.get("lang", "") in accepted_langs and i.get("url")
        ]
        if candidates:
            # prefer lang_pref first
            preferred = [i["url"] for i in candidates if i.get("lang") == lang_pref]
            art["clearlogo"] = preferred[:1] or [candidates[0]["url"]]
            break

    # clearart: first match wins
    for clearart_key in ("clearart", "hdclearart"):
        urls = pick_urls(clearart_key)
        if urls:
            art["clearart"] = urls
            break

    logger.debug(
        "fanart: got art types {} for thetvdb_id={}".format(
            list(art.keys()), thetvdb_id
        )
    )
    return art
