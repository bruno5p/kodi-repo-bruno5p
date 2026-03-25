import sys
import os

import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()
sys.path.insert(0, os.path.join(ADDON.getAddonInfo("path"), "resources", "lib"))

from logger import logger
from symlinker import rebuild
from scanner import get_anime_sources, scan_library

RUN_MODE_REINDEX_AND_SCAN = "0"
RUN_MODE_REINDEX_ONLY = "1"


def run():
    kodi_dir_name = ADDON.getSetting("kodi_dir_name") or "_kodi"
    run_mode = ADDON.getSetting("run_mode") or RUN_MODE_REINDEX_AND_SCAN

    logger.info("default: kodi_dir_name=%r run_mode=%r" % (kodi_dir_name, run_mode))

    anime_sources = get_anime_sources(kodi_dir_name)

    if not anime_sources:
        logger.warning("default: no anime sources found in Kodi video sources")
        xbmcgui.Dialog().ok(
            "Anime Library Manager",
            "No video sources with 'anime' in the path were found.\n\n"
            "Add your Anime folder (or its [B]%s[/B] subfolder) as a "
            "TV show source in Kodi first." % kodi_dir_name,
        )
        return

    mode_label = "Reindex and scan" if run_mode == RUN_MODE_REINDEX_AND_SCAN else "Reindex only"
    source_list = "\n".join("- %s" % root for root, _ in anime_sources)
    confirmed = xbmcgui.Dialog().yesno(
        "Anime Library Manager",
        "[B]%s[/B]\n\nReindex symlinks for:\n%s" % (mode_label, source_list),
    )
    if not confirmed:
        logger.debug("default: cancelled by user")
        return

    total_created = total_removed = total_errors = 0
    for anime_root, kodi_flat in anime_sources:
        logger.info("default: rebuilding symlinks for %r" % anime_root)
        try:
            created, removed, errors = rebuild(anime_root, kodi_dir_name)
            total_created += created
            total_removed += removed
            total_errors += errors
        except PermissionError as e:
            logger.error("default: %s" % e)
            xbmcgui.Dialog().ok("Anime Library Manager", str(e))
            return

    msg = "Symlinks: +%d created, -%d removed" % (total_created, total_removed)
    if total_errors:
        msg += ", %d errors" % total_errors
    logger.info("default: %s" % msg)
    xbmcgui.Dialog().notification("Anime Library Manager", msg, time=3000)

    if run_mode == RUN_MODE_REINDEX_AND_SCAN:
        scan_library()
    else:
        logger.info("default: skipping scan (reindex only mode)")


run()
