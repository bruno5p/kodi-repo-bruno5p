"""
Kodi action handlers for the anime MAL metadata scraper.

Kodi calls this scraper via plugin URL params:
  ?action=find&search=...
  ?action=nfourl&nfo=...
  ?action=getdetails&url=<mal_id>
  ?action=getepisodelist&url=<mal_id>&season=<n>
  ?action=getepisodedetails&url=<mal_id|ep|n or mal_id|special|related_id>
  ?action=getartwork&url=<mal_id>
"""

import json
import re
import xbmcgui

import xbmcplugin
import xbmcaddon

try:
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError, URLError
    from urllib.parse import urlencode
except ImportError:
    from urllib2 import urlopen, Request, HTTPError, URLError
    from urllib import urlencode

from resources.lib import jikan, utils, fanart as fanart_mod
from resources.lib.logger import logger

ADDON = xbmcaddon.Addon()

_TMDB_IMAGE_BASE    = "https://image.tmdb.org/t/p/original"
_TMDB_API_BASE      = "https://api.themoviedb.org/3"
# Embedded fallback key from plugin.video.tmdb.bingie.helper — used when no
# user key is configured in addon settings.
_TMDB_EMBEDDED_KEY  = "4f13072a99739d0780f37a524c15941d"


def _get_language_pref():
    try:
        return int(ADDON.getSetting("language"))
    except Exception:
        return utils.TITLE_LANG_ENGLISH


# ---------------------------------------------------------------------------
# TMDB artwork fetcher
# ---------------------------------------------------------------------------


def _fetch_tmdb_art(tmdb_id, media_type, api_key):
    """
    Fetch artwork from TMDB images endpoint.
    Returns dict: art_type -> list of full image URLs.
    Populated keys: 'fanart' (backdrops), 'clearlogo' (logos).
    Posters are intentionally skipped (MAL is the poster source).
    """
    params = urlencode({
        "api_key": api_key,
        "include_image_language": "ja,en,null",
    })
    url = "{}/{}/{}/images?{}".format(_TMDB_API_BASE, media_type, tmdb_id, params)
    logger.debug("tmdb: GET {}".format(url))

    try:
        req = Request(
            url,
            headers={"User-Agent": "metadata.anime.mal/1.0 (Kodi addon)"},
        )
        response = urlopen(req, timeout=10)
        res = json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        logger.error("tmdb: HTTP {} for tmdb_id={} media_type={} — check your API key".format(
            e.code, tmdb_id, media_type
        ))
        return {}
    except URLError as e:
        logger.error("tmdb: network error for tmdb_id={}: {}".format(tmdb_id, e))
        return {}

    # Log the top-level keys TMDB returned so we can see what's available
    logger.debug(
        "tmdb: response keys={} for {}/{} (backdrops={}, logos={}, posters={})".format(
            list(res.keys()),
            media_type, tmdb_id,
            len(res.get("backdrops") or []),
            len(res.get("logos") or []),
            len(res.get("posters") or []),
        )
    )

    art = {}

    # Backgrounds -> fanart
    # Sort: null/empty lang first (0), then "ja" (1), then "en" (2), rest (3)
    # Ties broken by vote_average descending
    backdrops = res.get("backdrops") or []
    if not backdrops:
        logger.debug("tmdb: no backdrops for {}/{}".format(media_type, tmdb_id))
    else:
        _LANG_ORDER = {"": 0, "ja": 1, "en": 2}

        def _bg_key(img):
            lang = img.get("iso_639_1") or ""  # null -> None -> ""
            return (_LANG_ORDER.get(lang, 3), -(img.get("vote_average") or 0.0))

        backdrops.sort(key=_bg_key)
        for img in backdrops:
            logger.debug(
                "tmdb: backdrop lang={!r} vote={} file={}".format(
                    img.get("iso_639_1"), img.get("vote_average", 0), img.get("file_path", "")
                )
            )
        art["fanart"] = [
            _TMDB_IMAGE_BASE + img["file_path"]
            for img in backdrops
            if img.get("file_path")
        ]
        logger.debug(
            "tmdb: {} backgrounds for {}/{}".format(len(art["fanart"]), media_type, tmdb_id)
        )

    # Logos -> clearlogo
    logos = res.get("logos") or []
    if not logos:
        logger.debug("tmdb: no logos for {}/{}".format(media_type, tmdb_id))
    else:
        logo_urls = [
            _TMDB_IMAGE_BASE + img["file_path"]
            for img in logos
            if img.get("file_path")
        ]
        if logo_urls:
            art["clearlogo"] = logo_urls
            logger.debug(
                "tmdb: {} logos for {}/{}".format(len(logo_urls), media_type, tmdb_id)
            )

    logger.debug(
        "tmdb: result art types={} for {}/{}".format(list(art.keys()), media_type, tmdb_id)
    )
    return art


def _fetch_external_art(mal_id):
    """
    Fetch external artwork from TMDB and/or Fanart.tv based on addon settings.
    Poster is always excluded (sourced from MAL).

    Returns:
        (other_art, fanart_list)
        other_art   — dict {art_type: [url, ...]} for clearlogo, clearart, etc.
        fanart_list — list of {"image": url, "preview": url} for backgrounds
    """
    art_source     = int(ADDON.getSetting("art_source") or "0")
    # User key takes priority; fall back to embedded key so TMDB works out-of-the-box
    tmdb_api_key   = ADDON.getSetting("tmdb_api_key").strip() or _TMDB_EMBEDDED_KEY
    fanart_api_key = ADDON.getSetting("fanarttv_api_key").strip()

    enabled_types = {
        "fanart":    ADDON.getSetting("fetch_fanart")    != "false",
        "clearlogo": ADDON.getSetting("fetch_clearlogo") != "false",
        "clearart":  ADDON.getSetting("fetch_clearart")  == "true",
        "banner":    ADDON.getSetting("fetch_banner")    == "true",
        "landscape": ADDON.getSetting("fetch_landscape") == "true",
        "thumbnail": ADDON.getSetting("fetch_thumbnail") == "true",
    }

    use_tmdb   = art_source in (0, 1)  # always available — embedded key is the fallback
    use_fanart = art_source in (0, 2) and bool(fanart_api_key)

    logger.debug(
        "_fetch_external_art: mal_id={} art_source={} use_tmdb={} use_fanart={} "
        "enabled_types={} fanart_key_set={}".format(
            mal_id, art_source, use_tmdb, use_fanart,
            {k: v for k, v in enabled_types.items() if v},
            bool(fanart_api_key),
        )
    )

    if not use_tmdb and not use_fanart:
        logger.debug("_fetch_external_art: no art source active (art_source={})".format(art_source))
        return {}, []

    lang      = _get_language_pref()
    lang_pref = "ja" if lang == utils.TITLE_LANG_JAPANESE else "en"

    ext_ids  = jikan.get_external_ids(mal_id)
    anidb_id = ext_ids.get("anidb_id")
    if not anidb_id:
        logger.warning("_fetch_external_art: no AniDB ID returned by Jikan for mal_id={} "
                       "— cannot map to TMDB or Fanart.tv".format(mal_id))
        return {}, []

    logger.debug("_fetch_external_art: anidb_id={} for mal_id={}".format(anidb_id, mal_id))

    tmdb_art   = {}
    fanart_art = {}

    if use_tmdb:
        tmdb_id, media_type = fanart_mod.anidb_to_tmdb(anidb_id)
        if tmdb_id:
            logger.debug(
                "_fetch_external_art: fetching TMDB {}/{} for anidb_id={}".format(
                    media_type, tmdb_id, anidb_id
                )
            )
            tmdb_art = _fetch_tmdb_art(tmdb_id, media_type, tmdb_api_key)
            if not tmdb_art:
                logger.warning(
                    "_fetch_external_art: TMDB returned no art for {}/{} (anidb_id={})".format(
                        media_type, tmdb_id, anidb_id
                    )
                )
        else:
            logger.warning(
                "_fetch_external_art: no TMDB ID in anime-list.xml for anidb_id={} "
                "(anime may not be in the mapping)".format(anidb_id)
            )

    if use_fanart:
        thetvdb_id = fanart_mod.anidb_to_thetvdb(anidb_id)
        # Guard: Fanart.tv needs a real numeric TheTVDB ID
        if thetvdb_id and thetvdb_id.isdigit():
            logger.debug(
                "_fetch_external_art: fetching Fanart.tv thetvdb_id={} for anidb_id={}".format(
                    thetvdb_id, anidb_id
                )
            )
            fanart_art = fanart_mod.get_artwork(thetvdb_id, fanart_api_key, lang_pref)
        else:
            logger.debug(
                "_fetch_external_art: skipping Fanart.tv — no numeric TheTVDB ID "
                "for anidb_id={} (got {!r})".format(anidb_id, thetvdb_id)
            )

    # Merge: for each type, TMDB primary; Fanart.tv fills gap (mode 0)
    merged = {}
    for art_type in ("fanart", "clearlogo", "clearart", "banner", "landscape"):
        if not enabled_types.get(art_type, False):
            logger.debug("_fetch_external_art: {} disabled in settings, skipping".format(art_type))
            continue
        if art_source == 1:
            urls = tmdb_art.get(art_type) or []
            source_used = "tmdb" if urls else "none"
        elif art_source == 2:
            urls = fanart_art.get(art_type) or []
            source_used = "fanart" if urls else "none"
        else:
            if tmdb_art.get(art_type):
                urls = tmdb_art[art_type]
                source_used = "tmdb"
            elif fanart_art.get(art_type):
                urls = fanart_art[art_type]
                source_used = "fanart (fallback)"
            else:
                urls = []
                source_used = "none"
        if urls:
            merged[art_type] = urls
        logger.debug(
            "_fetch_external_art: {} -> {} urls from {}".format(art_type, len(urls), source_used)
        )

    other_art   = {k: v for k, v in merged.items() if k != "fanart"}
    fanart_list = [{"image": u, "preview": u} for u in merged.get("fanart", [])]

    logger.debug(
        "_fetch_external_art: done — other_art={} fanart_count={}".format(
            list(other_art.keys()), len(fanart_list)
        )
    )
    return other_art, fanart_list


# ---------------------------------------------------------------------------
# find / search
# ---------------------------------------------------------------------------


def find(handle, params):
    """Search for anime by title and return a list of candidates."""
    query = params.get("title", "") or params.get("search", "")

    if not query:
        logger.warning("find: empty search query, returning empty directory")
        xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
        return

    logger.debug('find: query="{}"'.format(query))

    results = jikan.search(query)
    lang = _get_language_pref()
    logger.debug(
        "find: processing {} results (language pref={})".format(len(results), lang)
    )

    for anime in results:
        mal_id = str(anime.get("mal_id", ""))
        if not mal_id:
            continue

        title = utils.pick_title(anime.get("titles", []), lang)
        year = utils.extract_year(anime.get("aired"))
        image_url = utils.pick_image_url(anime.get("images", {}))

        logger.debug(
            'find: adding result mal_id={} title="{}" year={}'.format(
                mal_id, title, year
            )
        )

        item = xbmcgui.ListItem(title)
        item.setProperty("url", mal_id)
        item.setProperty("type", "tvshow")
        if year:
            item.setProperty("year", year)

        tag = item.getVideoInfoTag()
        tag.setMediaType("tvshow")
        tag.setTitle(title)
        tag.setPlot(anime.get("synopsis", ""))
        if year:
            tag.setYear(int(year))
        if image_url:
            item.setArt({"thumb": image_url})

        xbmcplugin.addDirectoryItem(handle, mal_id, item, isFolder=False)

    logger.debug("find: directory complete with {} items".format(len(results)))
    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)


# ---------------------------------------------------------------------------
# nfourl
# ---------------------------------------------------------------------------


def nfourl(handle, params):
    """
    Parse a tvshow.nfo file to extract a MAL ID or URL.
    Supports:
      - https://myanimelist.net/anime/1
      - https://myanimelist.net/anime/1/Cowboy_Bebop
      - Plain integer MAL ID anywhere in the file
    """
    nfo_content = params.get("nfo", "")
    logger.debug("nfourl: parsing NFO content ({} chars)".format(len(nfo_content)))

    mal_id = None

    match = re.search(r"myanimelist\.net/anime/(\d+)", nfo_content)
    if match:
        mal_id = match.group(1)
        logger.debug("nfourl: extracted mal_id={} from MAL URL".format(mal_id))

    if not mal_id:
        m = re.search(
            r'<uniqueid[^>]+type=["\']mal["\'][^>]*>\s*(\d+)\s*</uniqueid>',
            nfo_content,
            re.IGNORECASE,
        )
        if m:
            mal_id = m.group(1)
            logger.debug("nfourl: extracted mal_id={} from uniqueid tag".format(mal_id))

    if not mal_id:
        stripped = nfo_content.strip()
        if stripped.isdigit():
            mal_id = stripped
            logger.debug(
                "nfourl: extracted mal_id={} from plain numeric ID".format(mal_id)
            )

    if mal_id:
        item = xbmcgui.ListItem()
        item.setProperty("url", mal_id)
        xbmcplugin.addDirectoryItem(handle, "", item, isFolder=False)
    else:
        logger.warning("nfourl: could not extract MAL ID from NFO content")

    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)


# ---------------------------------------------------------------------------
# getdetails
# ---------------------------------------------------------------------------


def getdetails(handle, params):
    """Fetch full show metadata for a given MAL ID."""
    mal_id = params.get("url", "")
    logger.debug("getdetails: mal_id={}".format(mal_id))

    if not mal_id:
        logger.error("getdetails: missing url param")
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    anime = jikan.get_anime(mal_id)
    if not anime:
        logger.error("getdetails: no anime data returned for mal_id={}".format(mal_id))
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    lang = _get_language_pref()
    title = utils.pick_title(anime.get("titles", []), lang)
    orig_title = utils.pick_title(anime.get("titles", []), utils.TITLE_LANG_JAPANESE)
    year = utils.extract_year(anime.get("aired"))
    premiered = utils.extract_premiered(anime.get("aired"))
    genres = utils.collect_genres(anime)
    studios = utils.collect_studios(anime)
    status = utils.map_status(anime.get("status", ""))
    mpaa = utils.map_mpaa(anime.get("rating", ""))
    score = anime.get("score") or 0
    scored_by = anime.get("scored_by") or 0
    poster = utils.pick_image_url(anime.get("images", {}))
    episode_count = anime.get("episodes") or 0

    logger.debug(
        'getdetails: title="{}" year={} premiered={} status={} episodes={}'.format(
            title, year, premiered, status, episode_count
        )
    )
    logger.debug(
        'getdetails: genres={} studios={} score={} mpaa="{}"'.format(
            genres, studios, score, mpaa
        )
    )

    item = xbmcgui.ListItem(title)
    tag = item.getVideoInfoTag()
    tag.setUniqueIDs({"mal": str(anime["mal_id"])}, "mal")
    tag.setMediaType("tvshow")
    tag.setTitle(title)
    tag.setOriginalTitle(orig_title)
    tag.setPlot(anime.get("synopsis", ""))
    tag.setPlotOutline((anime.get("synopsis", "") or "")[:200])
    tag.setGenres(genres)
    tag.setTags(["anime"])
    tag.setTvShowStatus(status)
    if year:
        tag.setYear(int(year))
    if premiered:
        tag.setPremiered(premiered)
    if studios:
        tag.setStudios(studios)
    if mpaa:
        tag.setMpaa(mpaa)
    if episode_count:
        tag.setEpisode(episode_count)

    tag.setEpisodeGuide(str(mal_id))
    logger.debug("getdetails: episode guide set for mal_id={}".format(mal_id))

    if score:
        tag.setRating(score, scored_by, "mal", True)
        logger.debug("getdetails: set rating {}/10 ({} votes)".format(score, scored_by))

    if poster:
        tag.addAvailableArtwork(poster, "poster")
        tag.addAvailableArtwork(poster, "thumb")
        logger.debug("getdetails: poster set")

    # --- External artwork (TMDB and/or Fanart.tv) ---
    other_art, fanart_list = _fetch_external_art(mal_id)
    for art_type, urls in other_art.items():
        for url in urls:
            tag.addAvailableArtwork(url, art_type)
    for entry in fanart_list:
        tag.addAvailableArtwork(entry["image"], "fanart")
    logger.debug(
        "getdetails: added external art types: {}".format(
            list(other_art.keys()) + (["fanart"] if fanart_list else [])
        )
    )

    xbmcplugin.setResolvedUrl(handle, True, item)
    logger.debug("getdetails: resolved successfully for mal_id={}".format(mal_id))


# ---------------------------------------------------------------------------
# getepisodelist
# ---------------------------------------------------------------------------


def getepisodelist(handle, params):
    """Return episode stubs for a show."""
    mal_id = params.get("url", "")
    logger.debug("getepisodelist: mal_id={}".format(mal_id))

    if not mal_id:
        logger.error("getepisodelist: missing url param")
        xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
        return

    lang = _get_language_pref()
    _add_main_episodes(handle, mal_id, lang)
    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)


def _add_main_episodes(handle, mal_id, lang):
    """Add Season 1 episode stubs from the episodes endpoint."""
    episodes = jikan.get_episodes(mal_id)
    logger.debug(
        "_add_main_episodes: adding {} episodes for mal_id={}".format(
            len(episodes), mal_id
        )
    )

    if not episodes:
        # Movies, OVAs, and Specials often have no episode entries — synthesize ep 1
        anime = jikan.get_anime(mal_id)
        if anime:
            anime_type = anime.get("type", "unknown")
            logger.debug(
                "_add_main_episodes: no episodes for mal_id={} (type={}), "
                "synthesizing ep 1 from anime metadata".format(mal_id, anime_type)
            )
            title = utils.pick_title(anime.get("titles", []), lang) or anime.get("title", "Episode 1")
            aired = utils.extract_premiered(anime.get("aired")) or ""
            episode_url = utils.encode_episode_url(mal_id, 1)
            item = xbmcgui.ListItem(title)
            tag = item.getVideoInfoTag()
            tag.setMediaType("episode")
            tag.setTitle(title)
            tag.setSeason(1)
            tag.setEpisode(1)
            if aired:
                tag.setFirstAired(aired)
            xbmcplugin.addDirectoryItem(handle, episode_url, item, isFolder=False)
        else:
            logger.warning("_add_main_episodes: no episodes and no anime data for mal_id={}".format(mal_id))
        return

    for idx, ep in enumerate(episodes, start=1):
        ep_num = ep.get("mal_id") or idx
        title = (
            ep.get("title") or ep.get("title_romanji") or "Episode {}".format(ep_num)
        )
        aired = (ep.get("aired") or "")[:10]

        logger.debug(
            '_add_main_episodes: ep {} "{}" aired={}'.format(ep_num, title, aired)
        )

        episode_url = utils.encode_episode_url(mal_id, ep_num)
        item = xbmcgui.ListItem(title)
        tag = item.getVideoInfoTag()
        tag.setMediaType("episode")
        tag.setTitle(title)
        tag.setSeason(1)
        tag.setEpisode(ep_num)
        if aired:
            tag.setFirstAired(aired)
        xbmcplugin.addDirectoryItem(handle, episode_url, item, isFolder=False)



# ---------------------------------------------------------------------------
# getepisodedetails
# ---------------------------------------------------------------------------


def getepisodedetails(handle, params):
    """Return detailed metadata for a single episode or special."""
    url = params.get("url", "")
    logger.debug('getepisodedetails: url="{}"'.format(url))

    if not url:
        logger.error("getepisodedetails: missing url param")
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    decoded = utils.decode_url(url)
    lang = _get_language_pref()

    logger.debug(
        'getepisodedetails: decoded type="{}" mal_id={} value={}'.format(
            decoded["type"], decoded["mal_id"], decoded["value"]
        )
    )

    _resolve_main_episode(handle, decoded["mal_id"], decoded["value"], lang)


def _resolve_main_episode(handle, mal_id, episode_num, lang):
    """Resolve a regular series episode."""
    logger.debug("_resolve_main_episode: mal_id={} ep={}".format(mal_id, episode_num))

    try:
        target_num = int(episode_num)
    except ValueError:
        logger.error(
            '_resolve_main_episode: could not parse episode_num="{}"'.format(episode_num)
        )
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    ep = jikan.get_episode_detail(mal_id, target_num)
    if not ep:
        # Fallback for movies/OVAs/Specials: use anime-level metadata for ep 1
        logger.debug(
            "_resolve_main_episode: no episode detail for ep {} in mal_id={}, "
            "trying anime-level fallback".format(target_num, mal_id)
        )
        anime = jikan.get_anime(mal_id)
        if anime and target_num == 1:
            title = utils.pick_title(anime.get("titles", []), lang) or anime.get("title", "Episode 1")
            aired = utils.extract_premiered(anime.get("aired")) or ""
            synopsis = anime.get("synopsis", "")
            duration = _parse_duration(anime.get("duration", ""))
            logger.debug(
                '_resolve_main_episode: anime fallback title="{}" aired={} duration={}s'.format(
                    title, aired, duration
                )
            )
            item = xbmcgui.ListItem(title)
            tag = item.getVideoInfoTag()
            tag.setMediaType("episode")
            tag.setTitle(title)
            tag.setSeason(1)
            tag.setEpisode(1)
            if aired:
                tag.setFirstAired(aired)
            if synopsis:
                tag.setPlot(synopsis)
            if duration:
                tag.setDuration(duration)
            xbmcplugin.setResolvedUrl(handle, True, item)
            return
        logger.error(
            "_resolve_main_episode: no detail for episode {} in mal_id={}".format(
                target_num, mal_id
            )
        )
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    ep_num = ep.get("mal_id") or target_num
    title = ep.get("title") or ep.get("title_romanji") or "Episode {}".format(ep_num)
    aired = (ep.get("aired") or "")[:10]
    synopsis = ep.get("synopsis") or ""
    duration = ep.get("duration") or 0  # seconds

    logger.debug(
        '_resolve_main_episode: ep {} "{}" aired={} synopsis={} duration={}s'.format(
            ep_num, title, aired, bool(synopsis), duration
        )
    )

    item = xbmcgui.ListItem(title)
    tag = item.getVideoInfoTag()
    tag.setMediaType("episode")
    tag.setTitle(title)
    tag.setSeason(1)
    tag.setEpisode(ep_num)
    if aired:
        tag.setFirstAired(aired)
    if synopsis:
        tag.setPlot(synopsis)
    if duration:
        tag.setDuration(duration)
    xbmcplugin.setResolvedUrl(handle, True, item)



def _parse_duration(duration_str):
    """
    Parse Jikan duration string (e.g. '24 min per ep', '1 hr 50 min') to seconds.
    Returns int seconds, or 0 if unparseable.
    """
    if not duration_str:
        return 0
    total = 0
    hr_match = re.search(r"(\d+)\s*hr", duration_str)
    min_match = re.search(r"(\d+)\s*min", duration_str)
    if hr_match:
        total += int(hr_match.group(1)) * 3600
    if min_match:
        total += int(min_match.group(1)) * 60
    logger.debug('_parse_duration: "{}" -> {}s'.format(duration_str, total))
    return total


# ---------------------------------------------------------------------------
# getartwork
# ---------------------------------------------------------------------------


def getartwork(handle, params):
    """Return available artwork for a show."""
    mal_id = params.get("url", "") or params.get("id", "")
    logger.debug("getartwork: mal_id={}".format(mal_id))

    if not mal_id:
        logger.error("getartwork: missing url/id param")
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    item = xbmcgui.ListItem()
    tag = item.getVideoInfoTag()

    # --- External artwork (TMDB and/or Fanart.tv) ---
    other_art, fanart_list = _fetch_external_art(mal_id)
    for art_type, urls in other_art.items():
        for url in urls:
            tag.addAvailableArtwork(url, art_type)
    logger.debug("getartwork: external art types: {}".format(list(other_art.keys())))

    # --- MAL/Jikan pictures: poster always from MAL ---
    pictures = jikan.get_pictures(mal_id)
    logger.debug(
        "getartwork: processing {} Jikan pictures for mal_id={}".format(len(pictures), mal_id)
    )

    for idx, pic in enumerate(pictures):
        large = utils.pick_image_url(pic, prefer_large=True)
        small = utils.pick_image_url(pic, prefer_large=False)
        if not large and not small:
            logger.debug("getartwork: skipping picture {} (no usable URL)".format(idx))
            continue
        url = large or small
        if idx == 0:
            tag.addAvailableArtwork(url, "poster")
            tag.addAvailableArtwork(small or url, "thumb")
            logger.debug("getartwork: set poster from picture 0")
        else:
            fanart_list.append({"image": url, "preview": small or url})

    if fanart_list:
        item.setAvailableFanart(fanart_list)
        logger.debug("getartwork: set {} fanart entries".format(len(fanart_list)))

    xbmcplugin.setResolvedUrl(handle, True, item)
    logger.debug("getartwork: resolved successfully for mal_id={}".format(mal_id))
