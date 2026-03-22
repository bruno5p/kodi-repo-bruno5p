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

import re
import xbmcgui
import xbmcplugin
import xbmcaddon

from resources.lib import jikan, utils, fanart as fanart_mod
from resources.lib.logger import logger

ADDON = xbmcaddon.Addon()


def _get_language_pref():
    try:
        return int(ADDON.getSetting("language"))
    except Exception:
        return utils.TITLE_LANG_ENGLISH


def _include_specials():
    return ADDON.getSetting("include_specials") != "false"


# ---------------------------------------------------------------------------
# find / search
# ---------------------------------------------------------------------------


def find(handle, params):
    """Search for anime by title and return a list of candidates."""
    query = params.get("title", "") or params.get("search", "")
    logger.debug('find: query="{}"'.format(query))

    if not query:
        logger.warning("find: empty search query, returning empty directory")
        xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
        return

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
    else:
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

    # --- Fanart.tv artwork (clearlogo, clearart, fanart, banner, landscape) ---
    api_key = ADDON.getSetting("fanarttv_api_key").strip()
    if api_key:
        lang_pref = "ja" if lang == utils.TITLE_LANG_JAPANESE else "en"
        ext_ids = jikan.get_external_ids(mal_id)
        anidb_id = ext_ids.get("anidb_id")
        if anidb_id:
            thetvdb_id = fanart_mod.anidb_to_thetvdb(anidb_id)
            if thetvdb_id:
                fanart_art = fanart_mod.get_artwork(thetvdb_id, api_key, lang_pref)
                for art_type, urls in fanart_art.items():
                    for url in urls:
                        tag.addAvailableArtwork(url, art_type)
                logger.debug(
                    "getdetails: added Fanart.tv art types: {}".format(list(fanart_art.keys()))
                )
            else:
                logger.debug("getdetails: no TheTVDB mapping for anidb_id={}".format(anidb_id))
        else:
            logger.debug("getdetails: no AniDB ID found for mal_id={}".format(mal_id))
    else:
        logger.debug("getdetails: Fanart.tv API key not set, skipping")

    xbmcplugin.setResolvedUrl(handle, True, item)
    logger.debug("getdetails: resolved successfully for mal_id={}".format(mal_id))


# ---------------------------------------------------------------------------
# getepisodelist
# ---------------------------------------------------------------------------


def getepisodelist(handle, params):
    """
    Return episode stubs for a show.
    Season 0 → related movies/OVAs/specials.
    Season 1+ → main series episodes.
    """
    mal_id = params.get("url", "")
    try:
        season = int(params.get("season", "1"))
    except ValueError:
        season = 1

    logger.debug("getepisodelist: mal_id={} season={}".format(mal_id, season))

    if not mal_id:
        logger.error("getepisodelist: missing url param")
        xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
        return

    lang = _get_language_pref()

    if season == 0 and _include_specials():
        logger.debug("getepisodelist: fetching Season 0 specials/movies/OVAs")
        _add_specials_episodes(handle, mal_id, lang)
    else:
        logger.debug("getepisodelist: fetching Season {} main episodes".format(season))
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


def _add_specials_episodes(handle, mal_id, lang):
    """Add Season 0 episode stubs from related movies/OVAs/specials."""
    relations = jikan.get_relations(mal_id)
    logger.debug(
        "_add_specials_episodes: found {} relation groups for mal_id={}".format(
            len(relations), mal_id
        )
    )

    specials = []
    for relation in relations:
        relation_type = relation.get("relation", "?")
        entries = relation.get("entry", [])
        logger.debug(
            '_add_specials_episodes: relation "{}" has {} entries'.format(
                relation_type, len(entries)
            )
        )
        for entry in entries:
            if entry.get("type") != "anime":
                continue
            related_id = entry.get("mal_id")
            if not related_id:
                continue
            related_anime = jikan.get_anime(related_id)
            if not related_anime:
                logger.warning(
                    "_add_specials_episodes: could not fetch related mal_id={}".format(
                        related_id
                    )
                )
                continue
            anime_type = related_anime.get("type", "")
            if anime_type in utils.SPECIAL_ANIME_TYPES:
                logger.debug(
                    '_add_specials_episodes: including related mal_id={} type="{}" as special'.format(
                        related_id, anime_type
                    )
                )
                specials.append(related_anime)
            else:
                logger.debug(
                    '_add_specials_episodes: skipping related mal_id={} type="{}"'.format(
                        related_id, anime_type
                    )
                )

    def sort_key(a):
        return utils.extract_premiered(a.get("aired")) or "9999"

    specials.sort(key=sort_key)
    logger.debug(
        "_add_specials_episodes: {} specials to add for mal_id={}".format(
            len(specials), mal_id
        )
    )

    for idx, special in enumerate(specials, start=1):
        related_id = str(special["mal_id"])
        title = utils.pick_title(special.get("titles", []), lang)
        aired = utils.extract_premiered(special.get("aired"))
        anime_type = special.get("type", "Special")

        logger.debug(
            '_add_specials_episodes: S0E{} mal_id={} type="{}" title="{}" aired={}'.format(
                idx, related_id, anime_type, title, aired
            )
        )

        special_url = utils.encode_special_url(mal_id, related_id)
        item = xbmcgui.ListItem(title)
        tag = item.getVideoInfoTag()
        tag.setMediaType("episode")
        tag.setTitle(title)
        tag.setSeason(0)
        tag.setEpisode(idx)
        tag.setPlot(special.get("synopsis", ""))
        if aired:
            tag.setFirstAired(aired)

        poster = utils.pick_image_url(special.get("images", {}))
        if poster:
            item.setArt({"thumb": poster})

        xbmcplugin.addDirectoryItem(handle, special_url, item, isFolder=False)


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

    if decoded["type"] == "special":
        _resolve_special_episode(handle, decoded["mal_id"], decoded["value"], lang)
    else:
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


def _resolve_special_episode(handle, original_mal_id, related_mal_id, lang):
    """Resolve a movie/OVA/special episode."""
    logger.debug(
        "_resolve_special_episode: original_mal_id={} related_mal_id={}".format(
            original_mal_id, related_mal_id
        )
    )

    anime = jikan.get_anime(related_mal_id)
    if not anime:
        logger.error(
            "_resolve_special_episode: no data for related_mal_id={}".format(
                related_mal_id
            )
        )
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    title = utils.pick_title(anime.get("titles", []), lang)
    aired = utils.extract_premiered(anime.get("aired"))
    duration = anime.get("duration", "") or ""
    runtime = _parse_duration(duration)
    score = anime.get("score") or 0
    scored_by = anime.get("scored_by") or 0
    poster = utils.pick_image_url(anime.get("images", {}))

    logger.debug(
        '_resolve_special_episode: title="{}" aired={} runtime={}s score={}'.format(
            title, aired, runtime, score
        )
    )

    item = xbmcgui.ListItem(title)
    tag = item.getVideoInfoTag()
    tag.setUniqueIDs({"mal": str(anime["mal_id"])}, "mal")
    tag.setMediaType("episode")
    tag.setTitle(title)
    tag.setSeason(0)
    tag.setPlot(anime.get("synopsis", ""))
    if aired:
        tag.setFirstAired(aired)
    if runtime:
        tag.setDuration(runtime)

    if score:
        tag.setRating(score, scored_by, "mal", True)

    if poster:
        item.setArt({"thumb": poster})

    xbmcplugin.setResolvedUrl(handle, True, item)
    logger.debug(
        "_resolve_special_episode: resolved successfully for related_mal_id={}".format(
            related_mal_id
        )
    )


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

    # --- Fanart.tv artwork (clearlogo, clearart, fanart, banner, landscape) ---
    api_key = ADDON.getSetting("fanarttv_api_key").strip()
    if api_key:
        lang = _get_language_pref()
        lang_pref = "ja" if lang == utils.TITLE_LANG_JAPANESE else "en"
        ext_ids = jikan.get_external_ids(mal_id)
        anidb_id = ext_ids.get("anidb_id")
        if anidb_id:
            thetvdb_id = fanart_mod.anidb_to_thetvdb(anidb_id)
            if thetvdb_id:
                fanart_art = fanart_mod.get_artwork(thetvdb_id, api_key, lang_pref)
                for art_type, urls in fanart_art.items():
                    for url in urls:
                        tag.addAvailableArtwork(url, art_type)
                logger.debug(
                    "getartwork: added Fanart.tv art types: {}".format(list(fanart_art.keys()))
                )
            else:
                logger.debug("getartwork: no TheTVDB mapping for anidb_id={}".format(anidb_id))
        else:
            logger.debug("getartwork: no AniDB ID found for mal_id={}".format(mal_id))
    else:
        logger.debug("getartwork: Fanart.tv API key not set, skipping")

    # --- MAL/Jikan pictures (poster + additional fanart) ---
    pictures = jikan.get_pictures(mal_id)
    logger.debug(
        "getartwork: processing {} Jikan pictures for mal_id={}".format(len(pictures), mal_id)
    )

    fanart_list = []
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
