"""
script.tmdb.lists entry point.

Plugin source (browseable in widget configurator):
  plugin://script.tmdb.lists/               -> root: manage item + all configured lists
  plugin://script.tmdb.lists/?list_id=<id>  -> items for one list (for widgets)
  plugin://script.tmdb.lists/?action=manage -> opens management UI

Script actions (RunScript):
  RunScript(script.tmdb.lists)                      -> open management UI
  RunScript(script.tmdb.lists,update_all)            -> update all stale lists silently
  RunScript(script.tmdb.lists,update_list,<list_id>) -> update a specific list
  RunScript(script.tmdb.lists,show_url,<list_id>)    -> show widget URL for a list
"""

import sys

from resources.lib.logger import logger


def _plugin_root(handle):
    """List all configured lists as browseable folders, with a manage entry at the top."""
    import xbmc
    import xbmcgui
    import xbmcplugin
    from resources.lib import list_manager

    # "Manage Lists" entry — clicking it opens the management UI script
    manage_li = xbmcgui.ListItem(label="[Manage Lists...]")
    manage_li.setInfo("video", {"title": "[Manage Lists...]"})
    xbmcplugin.addDirectoryItem(
        handle, "plugin://script.tmdb.lists/?action=manage", manage_li, isFolder=True
    )

    lists = list_manager.load_lists()
    for entry in lists:
        label = entry.get("label", str(entry["id"]))
        url = "plugin://script.tmdb.lists/?list_id={}".format(entry["id"])
        li = xbmcgui.ListItem(label=label)
        li.setInfo("video", {"title": label})
        xbmcplugin.addDirectoryItem(handle, url, li, isFolder=True)

    xbmcplugin.endOfDirectory(handle, succeeded=True)


def _plugin_list_items(handle, list_id):
    """Serve items from the pre-built items JSON so skins can display the widget."""
    import json
    import xbmcgui
    import xbmcplugin
    import xbmcvfs
    from resources.lib import list_manager

    path = xbmcvfs.translatePath(list_manager.get_items_path(list_id))
    items_data = []
    if xbmcvfs.exists(path):
        try:
            with xbmcvfs.File(path, "r") as f:
                items_data = json.load(f)
        except (IOError, ValueError) as e:
            logger.error("default: plugin failed to read items file: {}".format(e))

    tmdb_type_map = {"show": "tv", "movie": "movie"}
    kodi_type_map = {"show": "tvshow", "movie": "movie"}

    xbmcplugin.setContent(handle, "videos")

    for item in items_data:
        title = item.get("title", "")
        mediatype = item.get("mediatype", "show")
        tmdb_id = item.get("id")
        release_year = item.get("release_year")
        poster_path = item.get("poster_path")

        tmdb_type = tmdb_type_map.get(mediatype, "tv")
        kodi_type = kodi_type_map.get(mediatype, "tvshow")

        url = "plugin://plugin.video.tmdb.bingie.helper/?info=details&tmdb_type={}&tmdb_id={}".format(
            tmdb_type, tmdb_id
        )

        li = xbmcgui.ListItem(label=title)
        info = {"title": title, "mediatype": kodi_type}
        if release_year:
            info["year"] = release_year
        li.setInfo("video", info)

        if poster_path:
            li.setArt({"poster": "https://image.tmdb.org/t/p/w500{}".format(poster_path)})

        xbmcplugin.addDirectoryItem(handle, url, li, isFolder=True)

    xbmcplugin.endOfDirectory(handle, succeeded=True)


if __name__ == "__main__":

    if sys.argv[0].startswith("plugin://"):
        # Plugin source mode — called by Kodi when widget URL or file browser opens the addon
        try:
            handle = int(sys.argv[1])
        except (IndexError, ValueError):
            pass
        else:
            from urllib.parse import parse_qs
            params = parse_qs(sys.argv[2].lstrip("?")) if len(sys.argv) > 2 else {}
            action = params.get("action", [None])[0]
            list_id_str = params.get("list_id", [None])[0]

            if action == "manage":
                # Launch the management script and return an empty (cancelled) directory
                import xbmc
                xbmc.executebuiltin("RunScript(script.tmdb.lists,show_lists)")
                import xbmcplugin
                xbmcplugin.endOfDirectory(handle, succeeded=False)

            elif list_id_str is not None:
                try:
                    _plugin_list_items(handle, int(list_id_str))
                except ValueError:
                    logger.error("default: invalid list_id in plugin URL: {}".format(list_id_str))

            else:
                _plugin_root(handle)

    else:
        # Script mode — RunScript(script.tmdb.lists, ...)
        action = sys.argv[1] if len(sys.argv) > 1 else ""
        list_id_arg = sys.argv[2] if len(sys.argv) > 2 else ""

        logger.info("default: started action='{}' list_id='{}'".format(action, list_id_arg))

        if action in ("", "show_lists"):
            from resources.lib import ui
            ui.show_management()

        elif action == "update_all":
            import xbmcgui
            import xbmcaddon
            from resources.lib import list_manager, list_builder
            from resources.lib.tmdb_api import resolve_api_key

            configured_key = xbmcaddon.Addon().getSetting("tmdb_api_key").strip()
            api_key, key_source = resolve_api_key(configured_key)
            if not api_key:
                xbmcgui.Dialog().notification(
                    "TMDb Lists", "No TMDb API key available (install Bingie Helper or set key in settings)",
                    xbmcgui.NOTIFICATION_ERROR, 4000,
                )
            else:
                lists = list_manager.load_lists()
                updated = 0
                for entry in lists:
                    if list_manager.needs_update(entry):
                        success = list_builder.build_list(entry, api_key)
                        if success:
                            list_manager.mark_updated(entry["id"])
                            updated += 1
                xbmcgui.Dialog().notification(
                    "TMDb Lists", "Updated {} list(s).".format(updated),
                    xbmcgui.NOTIFICATION_INFO, 3000,
                )

        elif action == "update_list" and list_id_arg:
            import xbmcaddon
            from resources.lib import list_manager, list_builder
            from resources.lib.tmdb_api import resolve_api_key

            configured_key = xbmcaddon.Addon().getSetting("tmdb_api_key").strip()
            api_key, _ = resolve_api_key(configured_key)
            try:
                list_id = int(list_id_arg)
            except ValueError:
                logger.error("default: invalid list_id '{}'".format(list_id_arg))
            else:
                lists = list_manager.load_lists()
                entry = next((e for e in lists if e["id"] == list_id), None)
                if entry and api_key:
                    success = list_builder.build_list(entry, api_key)
                    if success:
                        list_manager.mark_updated(list_id)
                elif not entry:
                    logger.warning("default: list_id {} not found".format(list_id))

        elif action == "show_url" and list_id_arg:
            from resources.lib import list_manager, ui

            try:
                list_id = int(list_id_arg)
            except ValueError:
                logger.error("default: invalid list_id '{}'".format(list_id_arg))
            else:
                lists = list_manager.load_lists()
                entry = next((e for e in lists if e["id"] == list_id), None)
                if entry:
                    ui.show_widget_url(entry)
                else:
                    logger.warning("default: list_id {} not found".format(list_id))
