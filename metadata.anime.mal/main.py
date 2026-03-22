"""
metadata.anime.mal - Kodi TV show metadata scraper for MyAnimeList.

Entry point called by Kodi with plugin URL:
  plugin://metadata.anime.mal/?action=<action>&<params>
"""

import sys
import xbmcplugin
import xbmc

try:
    from urllib.parse import parse_qs
except ImportError:
    from urlparse import parse_qs

from resources.lib.actions import find, nfourl, getdetails, getepisodelist, getepisodedetails, getartwork

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

    xbmc.log('metadata.anime.mal: action={} params={}'.format(action, params), xbmc.LOGDEBUG)

    handler = _ACTIONS.get(action)
    if handler:
        try:
            handler(HANDLE, params)
        except Exception as exc:
            xbmc.log('metadata.anime.mal: unhandled exception in action "{}": {}'.format(action, exc), xbmc.LOGERROR)
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False, cacheToDisc=False)
    else:
        xbmc.log('metadata.anime.mal: unknown action "{}"'.format(action), xbmc.LOGWARNING)
        xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


run()
