"""
Auto-update service for plugin.list.builder.
Runs once at Kodi startup (after login), checks all TMDb lists, updates stale ones.
Re-checks hourly to cover long sessions and daily-interval lists.
Smartplaylist sampler entries are always dynamic and are skipped.
"""

import xbmc
import xbmcaddon

from resources.lib.logger import logger
from resources.lib import list_manager, list_builder
from resources.lib.tmdb_api import resolve_api_key


class UpdateService(xbmc.Monitor):

    def run(self):
        logger.info("service: List Builder service started")

        # Wait for Kodi to finish loading before network calls
        self.waitForAbort(5)
        if self.abortRequested():
            return

        self._do_update_pass()

        # Re-check hourly; waitForAbort returns True on Kodi shutdown
        while not self.waitForAbort(3600):
            self._do_update_pass()

        logger.info("service: List Builder service stopping")

    def _do_update_pass(self):
        """Check all lists and update any that are stale."""
        addon = xbmcaddon.Addon()  # re-read each pass so settings changes are picked up

        if addon.getSetting("update_on_startup").lower() not in ("true", "1"):
            logger.debug("service: update_on_startup disabled, skipping")
            return

        configured_key = addon.getSetting("tmdb_api_key").strip()
        api_key, key_source = resolve_api_key(configured_key)
        if not api_key:
            logger.warning("service: no TMDb API key available (install Bingie Helper or configure key in settings)")
        elif key_source == "bingie":
            logger.debug("service: using Bingie Helper API key as fallback")

        lists = list_manager.load_lists()
        if not lists:
            logger.debug("service: no lists configured")
            return

        updated = 0
        failed = 0
        for entry in lists:
            if list_manager.needs_update(entry):
                entry_type = entry.get("type", "tmdb")
                if entry_type == "tmdb" and not api_key:
                    logger.debug("service: skipping tmdb list '{}' — no api key".format(
                        entry.get("label")))
                    continue
                logger.info("service: updating stale list '{}' id={}".format(
                    entry.get("label"), entry.get("id")))
                try:
                    success = list_builder.build_entry(entry, api_key)
                    if success:
                        list_manager.mark_updated(entry["id"])
                        updated += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.error("service: exception updating list id={}: {}".format(
                        entry.get("id"), e))
                    failed += 1

        if updated or failed:
            logger.info("service: update pass complete — updated={} failed={}".format(
                updated, failed))


if __name__ == "__main__":
    UpdateService().run()
