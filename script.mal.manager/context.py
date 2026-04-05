"""
Context menu entry point for MAL Manager.
Extracts the MAL ID from the selected list item and opens the status manager.
"""
import sys
import xbmc
import xbmcgui

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

from resources.lib.logger import logger
from resources.lib import ui


def _extract_mal_id(item):
    """
    Try to find the MAL ID for the selected list item.

    Priority:
      1. Unique ID 'mal'  — set by metadata.anime.mal scraper or Otaku library items.
      2. Otaku Testing plugin path — extract numeric MAL ID from the URL.
    """
    vinfo = item.getVideoInfoTag()

    mal_id = vinfo.getUniqueID('mal')
    if mal_id and mal_id.strip().isdigit():
        logger.debug("context: MAL ID from uniqueID: {}".format(mal_id.strip()))
        return mal_id.strip()

    path = item.getPath()
    if 'plugin.video.otaku.testing' in path:
        parsed = urlparse(path)
        parts = [p for p in parsed.path.split('/') if p]
        route_prefixes = {
            'anime_overview', 'watchlist_manager', 'find_relations',
            'find_recommendations', 'watch_order', 'play',
        }
        for i, part in enumerate(parts):
            if part in route_prefixes and i + 1 < len(parts):
                candidate = parts[i + 1].split('?')[0]
                if candidate.isdigit():
                    logger.debug("context: MAL ID from Otaku path: {}".format(candidate))
                    return candidate

    return None


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "malstatus"
    logger.debug("context: action={}".format(action))

    if action == "sync":
        logger.info("context: launching library sync dialog")
        ui.show_sync_dialog()
        return

    # Default: malstatus — open manager for the selected item
    item = sys.listitem
    mal_id = _extract_mal_id(item)

    if not mal_id:
        vinfo = item.getVideoInfoTag()
        title = vinfo.getTitle() or vinfo.getTVShowTitle() or ''
        suffix = " for: {}".format(title) if title else ""
        logger.warning("context: could not find MAL ID{}".format(suffix))
        xbmcgui.Dialog().notification(
            "MAL Manager",
            "Could not find MAL ID{}".format(suffix),
            xbmcgui.NOTIFICATION_WARNING,
            3000
        )
        return

    logger.info("context: launching manager for MAL ID {}".format(mal_id))
    xbmc.executebuiltin("RunScript(script.mal.manager,{})".format(mal_id))


if __name__ == "__main__":
    main()
