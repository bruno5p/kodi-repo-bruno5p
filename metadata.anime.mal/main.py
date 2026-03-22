"""
metadata.anime.mal - Kodi TV show metadata scraper for MyAnimeList.

Entry point called by Kodi with plugin URL:
  plugin://metadata.anime.mal/?action=<action>&<params>
"""

import sys
import xbmcplugin

try:
    from urllib.parse import parse_qs
except ImportError:
    from urlparse import parse_qs

from resources.lib.actions import find, nfourl, getdetails, getepisodelist, getepisodedetails, getartwork
from resources.lib.logger import logger

HANDLE = int(sys.argv[1])

_ACTIONS = {
    'find': find,
    'nfourl': nfourl,
    'getdetails': getdetails,
    'getepisodelist': getepisodelist,
    'getepisodedetails': getepisodedetails,
    'getartwork': getartwork,
}


def run():
    raw_params = sys.argv[2][1:] if len(sys.argv) > 2 else ''
    parsed = parse_qs(raw_params, keep_blank_values=True)
    params = {k: v[0] for k, v in parsed.items()}
    action = params.get('action', '').lower()

    logger.debug('Invoked: action="{}" params={}'.format(action, params))

    handler = _ACTIONS.get(action)
    if handler:
        try:
            handler(HANDLE, params)
            logger.debug('Action "{}" completed successfully'.format(action))
        except Exception as exc:
            logger.error('Unhandled exception in action "{}": {}'.format(action, exc))
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False, cacheToDisc=False)
    else:
        logger.warning('Unknown action "{}"'.format(action))
        xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


run()
