"""
Query the local Kodi library for TV shows or movies matching a given unique ID.
Uses client-side filtering because uniqueid is not a supported JSON-RPC filter field.
"""
import json
import xbmc
from resources.lib.logger import logger


def find_local(media_type, media_id, id_type_name):
    """
    Search the local Kodi library for a media item.

    media_type:   'anime', 'tvshow', or 'movie'
    media_id:     the ID value to match (string or int)
    id_type_name: 'mal' or 'tmdb'

    Returns the first matching item dict or None.
    """
    media_id = str(media_id)
    if media_type in ("anime", "tvshow"):
        return _find_tvshow(id_type_name, media_id)
    elif media_type == "movie":
        return _find_movie(id_type_name, media_id)
    logger.warning("library: unknown media_type '{}'".format(media_type))
    return None


def _find_tvshow(id_type_name, media_id):
    query = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "VideoLibrary.GetTVShows",
        "params": {
            "properties": ["title", "file", "uniqueid"]
        }
    })
    logger.debug("library: searching tvshows by {}={}".format(id_type_name, media_id))
    raw = xbmc.executeJSONRPC(query)
    result = json.loads(raw)
    for show in result.get("result", {}).get("tvshows", []):
        unique_ids = show.get("uniqueid", {})
        if str(unique_ids.get(id_type_name, "")) == media_id:
            logger.debug("library: found tvshow '{}' for {}={}".format(
                show.get("title"), id_type_name, media_id))
            return show
    logger.debug("library: no tvshow found for {}={}".format(id_type_name, media_id))
    return None


def find_episode(id_type_name, mal_id, episode_num):
    """
    Find a specific episode in the local library by show unique ID and episode number.

    id_type_name: 'mal' or 'tmdb'
    mal_id:       the show ID value (string or int)
    episode_num:  the episode number (string or int)

    Returns the matching episode dict or None.
    """
    show = _find_tvshow(id_type_name, str(mal_id))
    if not show:
        return None
    tvshow_id = show.get("tvshowid")
    if not tvshow_id:
        return None
    query = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "VideoLibrary.GetEpisodes",
        "params": {
            "tvshowid": tvshow_id,
            "properties": ["title", "file", "season", "episode"],
        }
    })
    raw = xbmc.executeJSONRPC(query)
    result = json.loads(raw)
    episode_num_str = str(episode_num)
    for ep in result.get("result", {}).get("episodes", []):
        if str(ep.get("episode", "")) == episode_num_str:
            logger.debug("library: found episode {} for show '{}'".format(
                episode_num, show.get("title")))
            return ep
    logger.debug("library: episode {} not found for show '{}'".format(
        episode_num, show.get("title")))
    return None


def _find_movie(id_type_name, media_id):
    query = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "VideoLibrary.GetMovies",
        "params": {
            "properties": ["title", "file", "uniqueid"]
        }
    })
    logger.debug("library: searching movies by {}={}".format(id_type_name, media_id))
    raw = xbmc.executeJSONRPC(query)
    result = json.loads(raw)
    for movie in result.get("result", {}).get("movies", []):
        unique_ids = movie.get("uniqueid", {})
        if str(unique_ids.get(id_type_name, "")) == media_id:
            logger.debug("library: found movie '{}' for {}={}".format(
                movie.get("title"), id_type_name, media_id))
            return movie
    logger.debug("library: no movie found for {}={}".format(id_type_name, media_id))
    return None
