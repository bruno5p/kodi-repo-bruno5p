"""
Core routing logic: read settings, check local library, dispatch playback.

Call convention (via RunScript):
  RunScript(script.media.router, <media_type>, <media_id>)

  media_type : anime | anime_episode | tvshow | movie
  media_id   : the ID value (MAL ID, TMDB ID, or full Otaku play path for anime_episode)

Legacy single-arg call (anime assumed):
  RunScript(script.media.router, <mal_id>)

Settings enum indices:
  general.play_mode  : 0=Always Local, 1=Always Stream, 2=Always Choose
  <type>.play_mode   : 0=Use General Default, 1=Always Local, 2=Always Stream, 3=Always Choose
  anime.id_type      : 0=MAL, 1=TMDB
  tvshows.id_type    : 0=TMDB, 1=MAL
  movies.id_type     : 0=TMDB, 1=MAL
"""
import re
import xbmc
import xbmcgui
import xbmcaddon
from resources.lib.logger import logger
from resources.lib import library

ADDON = xbmcaddon.Addon()

# Resolved play modes
PLAY_LOCAL = 0
PLAY_STREAM = 1
PLAY_CHOOSE = 2


def _setting_int(key):
    """Read an enum/integer setting as int, defaulting to 0."""
    return int(ADDON.getSetting(key) or "0")


def _get_play_mode(media_type):
    """
    Returns the resolved PLAY_* constant for the given media type.
    Category setting '0' means 'use general default'.
    Category indices 1/2/3 map to PLAY_LOCAL/STREAM/CHOOSE (subtract 1).
    """
    key_map = {
        "anime":  "anime.play_mode",
        "tvshow": "tvshows.play_mode",
        "movie":  "movies.play_mode",
    }
    key = key_map.get(media_type)
    if key:
        cat_mode = _setting_int(key)
        if cat_mode == 0:  # Use General Default
            return _setting_int("general.play_mode")
        return cat_mode - 1  # 1→0(local), 2→1(stream), 3→2(choose)
    return _setting_int("general.play_mode")


def _get_id_type_name(media_type):
    """
    Returns the library uniqueid key name ('mal' or 'tmdb') for the media type.
    Note: metadata.anime.mal scrapes with key 'mal'; TMDb scrapers use 'tmdb'.
    """
    if media_type == "anime":
        return "mal" if _setting_int("anime.id_type") == 0 else "tmdb"
    elif media_type == "tvshow":
        return "tmdb" if _setting_int("tvshows.id_type") == 0 else "mal"
    elif media_type == "movie":
        return "tmdb" if _setting_int("movies.id_type") == 0 else "mal"
    return "tmdb"


def run(media_type, media_id):
    if media_type == "anime_episode":
        _run_anime_episode(media_id)
        return

    if media_type == "check_local":
        _check_local(media_id)
        return

    if not media_id:
        xbmcgui.Dialog().notification(
            "Media Router", "No media ID provided",
            xbmcgui.NOTIFICATION_WARNING, 3000
        )
        logger.warning("router: no media_id provided")
        return

    play_mode = _get_play_mode(media_type)
    id_type_name = _get_id_type_name(media_type)

    logger.info("router: type={} id={} play_mode={} id_type={}".format(
        media_type, media_id, play_mode, id_type_name))

    local_item = library.find_local(media_type, media_id, id_type_name)

    if play_mode == PLAY_LOCAL:
        if local_item:
            _play_local(local_item)
        else:
            xbmcgui.Dialog().notification(
                "Media Router", "Not found in local library",
                xbmcgui.NOTIFICATION_WARNING, 3000
            )
            logger.warning("router: no local copy for {} id={}".format(media_type, media_id))

    elif play_mode == PLAY_STREAM:
        _play_stream(media_type, media_id, id_type_name)

    elif play_mode == PLAY_CHOOSE:
        _show_choice(media_type, media_id, id_type_name, local_item)


def _show_choice(media_type, media_id, id_type_name, local_item):
    title = local_item.get("title", media_id) if local_item else str(media_id)
    options = []
    if local_item:
        options.append(("Play Local", lambda: _play_local(local_item)))
    options.append(("Stream", lambda: _play_stream(media_type, media_id, id_type_name)))

    labels = [o[0] for o in options]
    choice = xbmcgui.Dialog().select("Play \u2014 {}".format(title), labels)
    if choice >= 0:
        options[choice][1]()


def _play_local(item):
    path = item.get("file", "")
    title = item.get("title", "")
    logger.info("router: playing local '{}' from {}".format(title, path))
    xbmc.executebuiltin("ActivateWindow(Videos,{},return)".format(path))


def _play_stream(media_type, media_id, id_type_name):
    logger.info("router: streaming {} id={} (id_type={})".format(
        media_type, media_id, id_type_name))

    if media_type == "anime":
        xbmc.executebuiltin(
            "ActivateWindow(Videos,"
            "plugin://plugin.video.otaku.testing/animes/{}/,"
            "return)".format(media_id)
        )

    elif media_type == "tvshow":
        if id_type_name == "tmdb":
            xbmc.executebuiltin(
                "ActivateWindow(Videos,"
                "plugin://plugin.video.themoviedb.helper/?info=seasons&type=tv&tmdb={},"
                "return)".format(media_id)
            )
        else:
            xbmc.executebuiltin(
                "ActivateWindow(Videos,"
                "plugin://plugin.video.otaku.testing/animes/{}/,"
                "return)".format(media_id)
            )

    elif media_type == "movie":
        if id_type_name == "tmdb":
            xbmc.executebuiltin(
                "RunPlugin(plugin://plugin.video.themoviedb.helper/"
                "?info=play&type=movie&tmdb={})".format(media_id)
            )
        else:
            logger.warning("router: no MAL-based movie streaming configured")
            xbmcgui.Dialog().notification(
                "Media Router", "No MAL streaming configured for movies",
                xbmcgui.NOTIFICATION_WARNING, 3000
            )


def _check_local(mal_id):
    """
    Check if an Otaku anime exists in the local library.
    Sets Window(Home).Property(OtakuLocalEpisodesPath) to the videodb episodes path if found,
    or clears it if not found. Called on info dialog open for Otaku items.
    """
    id_type_name = _get_id_type_name("anime")
    show = library.find_local("anime", mal_id, id_type_name)
    home = xbmcgui.Window(10000)
    if show:
        tvshow_id = show.get("tvshowid", "")
        if tvshow_id:
            path = "videodb://tvshows/titles/{}/-2/".format(tvshow_id)
            home.setProperty("OtakuLocalEpisodesPath", path)
            logger.debug("router: check_local found show for mal_id={} path={}".format(mal_id, path))
            return
    home.clearProperty("OtakuLocalEpisodesPath")
    logger.debug("router: check_local no local show for mal_id={}".format(mal_id))


def _run_anime_episode(otaku_path):
    """
    Route an Otaku anime episode via its play path.
    Parses mal_id and episode number from the path, checks local library,
    and offers Play Local or Stream based on play_mode setting.

    otaku_path examples:
      plugin://plugin.video.otaku.testing/play/39198/1
      plugin://plugin.video.otaku.testing/play_movie/39198/
    """
    m = re.search(r'/play(?:_movie)?/(\d+)/?(\d*)', otaku_path)
    if not m:
        logger.warning("router: unrecognized otaku play path: {}".format(otaku_path))
        return

    mal_id = m.group(1)
    episode_num = m.group(2) or "1"
    play_mode = _get_play_mode("anime")
    id_type_name = _get_id_type_name("anime")

    logger.info("router: anime_episode mal_id={} ep={} play_mode={}".format(
        mal_id, episode_num, play_mode))

    local_episode = library.find_episode(id_type_name, mal_id, episode_num)

    if play_mode == PLAY_LOCAL:
        if local_episode:
            _play_local_episode(local_episode)
        else:
            xbmcgui.Dialog().notification(
                "Media Router", "Episode not in local library",
                xbmcgui.NOTIFICATION_WARNING, 3000
            )
            logger.warning("router: episode {} not in library for mal_id={}".format(
                episode_num, mal_id))

    elif play_mode == PLAY_STREAM:
        xbmc.executebuiltin("PlayMedia({})".format(otaku_path))

    elif play_mode == PLAY_CHOOSE:
        ep_title = local_episode.get("title", "") if local_episode else ""
        label = ep_title or "Episode {}".format(episode_num)
        options = []
        if local_episode:
            options.append(("Play Local", lambda: _play_local_episode(local_episode)))
        options.append(("Stream", lambda: xbmc.executebuiltin(
            "PlayMedia({})".format(otaku_path))))

        labels = [o[0] for o in options]
        choice = xbmcgui.Dialog().select(
            "Play \u2014 {}".format(label), labels)
        if choice >= 0:
            options[choice][1]()


def _play_local_episode(episode_item):
    path = episode_item.get("file", "")
    title = episode_item.get("title", "")
    logger.info("router: playing local episode '{}' from {}".format(title, path))
    xbmc.executebuiltin('PlayMedia("{}")'.format(path))
