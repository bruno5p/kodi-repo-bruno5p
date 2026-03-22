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

from resources.lib import jikan, utils

ADDON = xbmcaddon.Addon()


def _get_language_pref():
    try:
        return int(ADDON.getSetting('language'))
    except Exception:
        return utils.TITLE_LANG_ENGLISH


def _include_specials():
    return ADDON.getSetting('include_specials') != 'false'


# ---------------------------------------------------------------------------
# find / search
# ---------------------------------------------------------------------------

def find(handle, params):
    """Search for anime by title and return a list of candidates."""
    query = params.get('search', '')
    if not query:
        xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
        return

    results = jikan.search(query)
    lang = _get_language_pref()

    for anime in results:
        mal_id = str(anime.get('mal_id', ''))
        if not mal_id:
            continue

        title = utils.pick_title(anime.get('titles', []), lang)
        year = utils.extract_year(anime.get('aired'))
        anime_type = anime.get('type', '')
        image_url = utils.pick_image_url(anime.get('images', {}))

        item = xbmcgui.ListItem(title)
        item.setProperty('url', mal_id)
        item.setProperty('type', 'tvshow')
        if year:
            item.setProperty('year', year)

        # Brief info so Kodi can display search results
        item.setInfo('video', {
            'title': title,
            'year': int(year) if year else 0,
            'plot': anime.get('synopsis', ''),
        })
        if image_url:
            item.setArt({'thumb': image_url})

        xbmcplugin.addDirectoryItem(handle, '', item, isFolder=False)

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
    nfo_content = params.get('nfo', '')

    mal_id = None

    # Try MAL URL pattern first
    match = re.search(r'myanimelist\.net/anime/(\d+)', nfo_content)
    if match:
        mal_id = match.group(1)
    else:
        # Try plain numeric ID as only content (trim whitespace)
        stripped = nfo_content.strip()
        if stripped.isdigit():
            mal_id = stripped

    if mal_id:
        item = xbmcgui.ListItem()
        item.setProperty('url', mal_id)
        xbmcplugin.addDirectoryItem(handle, '', item, isFolder=False)

    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)


# ---------------------------------------------------------------------------
# getdetails
# ---------------------------------------------------------------------------

def getdetails(handle, params):
    """Fetch full show metadata for a given MAL ID."""
    mal_id = params.get('url', '')
    if not mal_id:
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    anime = jikan.get_anime(mal_id)
    if not anime:
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    lang = _get_language_pref()
    title = utils.pick_title(anime.get('titles', []), lang)
    orig_title = utils.pick_title(anime.get('titles', []), utils.TITLE_LANG_JAPANESE)
    year = utils.extract_year(anime.get('aired'))
    premiered = utils.extract_premiered(anime.get('aired'))
    genres = utils.collect_genres(anime)
    studios = utils.collect_studios(anime)
    status = utils.map_status(anime.get('status', ''))
    mpaa = utils.map_mpaa(anime.get('rating', ''))
    score = anime.get('score') or 0
    scored_by = anime.get('scored_by') or 0
    poster = utils.pick_image_url(anime.get('images', {}))
    episode_count = anime.get('episodes') or 0

    item = xbmcgui.ListItem(title)

    item.setUniqueIDs({'mal': str(anime['mal_id'])}, defaultUniqueID='mal')

    info = {
        'title': title,
        'originaltitle': orig_title,
        'plot': anime.get('synopsis', ''),
        'plotoutline': anime.get('synopsis', '')[:200] if anime.get('synopsis') else '',
        'genre': genres,
        'status': status,
        'mediatype': 'tvshow',
    }
    if year:
        info['year'] = int(year)
    if premiered:
        info['premiered'] = premiered
    if studios:
        info['studio'] = studios
    if mpaa:
        info['mpaa'] = mpaa
    if episode_count:
        info['episode'] = episode_count

    item.setInfo('video', info)

    if score:
        item.setRating('mal', score, scored_by, defaultrating=True)

    art = {}
    if poster:
        art['poster'] = poster
        art['thumb'] = poster
    item.setArt(art)

    xbmcplugin.setResolvedUrl(handle, True, item)


# ---------------------------------------------------------------------------
# getepisodelist
# ---------------------------------------------------------------------------

def getepisodelist(handle, params):
    """
    Return episode stubs for a show.
    Season 0 → related movies/OVAs/specials.
    Season 1+ → main series episodes.
    """
    mal_id = params.get('url', '')
    try:
        season = int(params.get('season', '1'))
    except ValueError:
        season = 1

    if not mal_id:
        xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
        return

    lang = _get_language_pref()

    if season == 0 and _include_specials():
        _add_specials_episodes(handle, mal_id, lang)
    else:
        _add_main_episodes(handle, mal_id, lang)

    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)


def _add_main_episodes(handle, mal_id, lang):
    """Add Season 1 episode stubs from the episodes endpoint."""
    episodes = jikan.get_episodes(mal_id)
    for idx, ep in enumerate(episodes, start=1):
        ep_num = ep.get('mal_id') or idx
        title = ep.get('title') or ep.get('title_romanji') or 'Episode {}'.format(ep_num)
        aired = (ep.get('aired') or '')[:10]

        item = xbmcgui.ListItem(title)
        item.setProperty('url', utils.encode_episode_url(mal_id, ep_num))

        info = {
            'title': title,
            'season': 1,
            'episode': ep_num,
            'mediatype': 'episode',
        }
        if aired:
            info['aired'] = aired

        item.setInfo('video', info)
        xbmcplugin.addDirectoryItem(handle, '', item, isFolder=False)


def _add_specials_episodes(handle, mal_id, lang):
    """Add Season 0 episode stubs from related movies/OVAs/specials."""
    relations = jikan.get_relations(mal_id)
    specials = []

    for relation in relations:
        for entry in relation.get('entry', []):
            if entry.get('type') != 'anime':
                continue
            related_id = entry.get('mal_id')
            if not related_id:
                continue
            # Fetch the related anime to check its type
            related_anime = jikan.get_anime(related_id)
            if not related_anime:
                continue
            if related_anime.get('type') in utils.SPECIAL_ANIME_TYPES:
                specials.append(related_anime)

    # Sort by air date so specials appear chronologically
    def sort_key(a):
        return utils.extract_premiered(a.get('aired')) or '9999'

    specials.sort(key=sort_key)

    for idx, special in enumerate(specials, start=1):
        related_id = str(special['mal_id'])
        title = utils.pick_title(special.get('titles', []), lang)
        aired = utils.extract_premiered(special.get('aired'))
        anime_type = special.get('type', 'Special')

        item = xbmcgui.ListItem(title)
        item.setProperty('url', utils.encode_special_url(mal_id, related_id))

        info = {
            'title': title,
            'season': 0,
            'episode': idx,
            'mediatype': 'episode',
            'plot': special.get('synopsis', ''),
        }
        if aired:
            info['aired'] = aired

        item.setInfo('video', info)

        poster = utils.pick_image_url(special.get('images', {}))
        if poster:
            item.setArt({'thumb': poster})

        xbmcplugin.addDirectoryItem(handle, '', item, isFolder=False)


# ---------------------------------------------------------------------------
# getepisodedetails
# ---------------------------------------------------------------------------

def getepisodedetails(handle, params):
    """Return detailed metadata for a single episode or special."""
    url = params.get('url', '')
    if not url:
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    decoded = utils.decode_url(url)
    lang = _get_language_pref()

    if decoded['type'] == 'special':
        _resolve_special_episode(handle, decoded['mal_id'], decoded['value'], lang)
    else:
        _resolve_main_episode(handle, decoded['mal_id'], decoded['value'], lang)


def _resolve_main_episode(handle, mal_id, episode_num, lang):
    """Resolve a regular series episode."""
    episodes = jikan.get_episodes(mal_id)
    target = None
    try:
        target_num = int(episode_num)
    except ValueError:
        target_num = None

    for ep in episodes:
        if ep.get('mal_id') == target_num:
            target = ep
            break

    if not target:
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    ep_num = target.get('mal_id') or target_num
    title = target.get('title') or target.get('title_romanji') or 'Episode {}'.format(ep_num)
    aired = (target.get('aired') or '')[:10]

    item = xbmcgui.ListItem(title)
    info = {
        'title': title,
        'season': 1,
        'episode': ep_num,
        'mediatype': 'episode',
    }
    if aired:
        info['aired'] = aired

    item.setInfo('video', info)
    xbmcplugin.setResolvedUrl(handle, True, item)


def _resolve_special_episode(handle, original_mal_id, related_mal_id, lang):
    """Resolve a movie/OVA/special episode."""
    anime = jikan.get_anime(related_mal_id)
    if not anime:
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    title = utils.pick_title(anime.get('titles', []), lang)
    aired = utils.extract_premiered(anime.get('aired'))
    duration = anime.get('duration', '') or ''
    runtime = _parse_duration(duration)
    score = anime.get('score') or 0
    scored_by = anime.get('scored_by') or 0
    poster = utils.pick_image_url(anime.get('images', {}))

    item = xbmcgui.ListItem(title)
    item.setUniqueIDs({'mal': str(anime['mal_id'])}, defaultUniqueID='mal')

    info = {
        'title': title,
        'season': 0,
        'mediatype': 'episode',
        'plot': anime.get('synopsis', ''),
    }
    if aired:
        info['aired'] = aired
    if runtime:
        info['duration'] = runtime

    item.setInfo('video', info)

    if score:
        item.setRating('mal', score, scored_by, defaultrating=True)

    if poster:
        item.setArt({'thumb': poster})

    xbmcplugin.setResolvedUrl(handle, True, item)


def _parse_duration(duration_str):
    """
    Parse Jikan duration string (e.g. '24 min per ep', '1 hr 50 min') to seconds.
    Returns int seconds, or 0 if unparseable.
    """
    if not duration_str:
        return 0
    total = 0
    hr_match = re.search(r'(\d+)\s*hr', duration_str)
    min_match = re.search(r'(\d+)\s*min', duration_str)
    if hr_match:
        total += int(hr_match.group(1)) * 3600
    if min_match:
        total += int(min_match.group(1)) * 60
    return total


# ---------------------------------------------------------------------------
# getartwork
# ---------------------------------------------------------------------------

def getartwork(handle, params):
    """Return available artwork for a show."""
    mal_id = params.get('url', '')
    if not mal_id:
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    pictures = jikan.get_pictures(mal_id)

    item = xbmcgui.ListItem()
    fanart_list = []

    for idx, pic in enumerate(pictures):
        large = utils.pick_image_url(pic, prefer_large=True)
        small = utils.pick_image_url(pic, prefer_large=False)
        if not large and not small:
            continue
        url = large or small
        if idx == 0:
            item.addAvailableArtwork(url, 'poster')
            item.addAvailableArtwork(small or url, 'thumb')
        else:
            fanart_list.append({'image': url, 'preview': small or url})

    if fanart_list:
        item.setAvailableFanart(fanart_list)

    xbmcplugin.setResolvedUrl(handle, True, item)
