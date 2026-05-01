"""
Kodi UI dialogs for MAL Manager.
"""
import xbmc
import xbmcgui
import xbmcaddon

from resources.lib.logger import logger
from resources.lib import auth, mal_api

ADDON = xbmcaddon.Addon()

ACTIONS = [
    "Update from MAL",
    "Update to MAL",
    "Reset to MAL status",
    "Mark as Watching",
    "Update Episodes Watched",
    "Mark as Completed",
    "Update Score",
    "Change Status",
    "Add to Plan to Watch",
]


def show_manager(mal_id):
    """Main entry point: check auth, fetch status, show action dialog."""
    if not mal_id:
        xbmcgui.Dialog().notification("MAL Manager", "No MAL ID provided", xbmcgui.NOTIFICATION_WARNING, 3000)
        logger.warning("ui: show_manager called with no mal_id")
        return

    access_token = auth.get_access_token()
    if not access_token:
        go_auth = xbmcgui.Dialog().yesno(
            "MAL Manager",
            "Not authenticated with MyAnimeList.[CR][CR]"
            "If you are already logged into [B]Otaku Testing[/B] with MAL, "
            "re-open this after a moment — credentials are shared automatically.[CR][CR]"
            "Otherwise, press [B]Authorize[/B] to log in now.",
            yeslabel="Authorize",
            nolabel="Cancel"
        )
        if go_auth:
            auth.run_auth_flow()
        return

    # Fetch current status for context
    current = mal_api.get_anime_list_status(mal_id)
    current_status = current.get("status", "not in list") if current else "not in list"
    current_score = current.get("score", 0) if current else 0
    current_watched = current.get("num_episodes_watched", 0) if current else 0

    username = auth.get_username()
    user_str = "  [{}]".format(username) if username else ""
    header = "MAL Manager{}  [MAL ID: {}]".format(user_str, mal_id)
    subtitle = "Status: {}  |  Score: {}  |  Watched: {} ep".format(
        mal_api.STATUS_LABELS.get(current_status, current_status),
        current_score if current_score else "—",
        current_watched
    )

    choice = xbmcgui.Dialog().select(
        "{}\n{}".format(header, subtitle),
        ACTIONS
    )

    if choice == 0:
        _sync_single_item(mal_id, "from_mal")
    elif choice == 1:
        _sync_single_item(mal_id, "to_mal")
    elif choice == 2:
        _sync_single_item(mal_id, "force_from_mal")
    elif choice == 3:
        _set_status(mal_id, mal_api.STATUS_WATCHING)
    elif choice == 4:
        _update_episodes(mal_id, current_watched)
    elif choice == 5:
        _set_status(mal_id, mal_api.STATUS_COMPLETED)
    elif choice == 6:
        _update_score(mal_id, current_score)
    elif choice == 7:
        _change_status(mal_id, current_status)
    elif choice == 8:
        _set_status(mal_id, mal_api.STATUS_PLAN_TO_WATCH)
    # choice == -1: cancelled


def _set_status(mal_id, status):
    result = mal_api.update_anime_status(mal_id, status=status)
    label = mal_api.STATUS_LABELS.get(status, status)
    if result:
        logger.info("ui: status set to '{}' for mal_id={}".format(status, mal_id))
        xbmcgui.Dialog().notification("MAL Manager", "Status updated: {}".format(label), xbmcgui.NOTIFICATION_INFO, 3000)
    else:
        xbmcgui.Dialog().notification("MAL Manager", "Failed to update status", xbmcgui.NOTIFICATION_ERROR, 3000)


def _update_episodes(mal_id, current_watched):
    ep_str = xbmcgui.Dialog().input(
        "Episodes watched",
        str(current_watched) if current_watched else "0",
        type=xbmcgui.INPUT_NUMERIC
    )
    if ep_str is None or ep_str == "":
        return
    try:
        num_watched = int(ep_str)
        if num_watched < 0:
            raise ValueError("negative")
    except ValueError:
        xbmcgui.Dialog().notification("MAL Manager", "Invalid number of episodes", xbmcgui.NOTIFICATION_WARNING, 3000)
        return

    result = mal_api.update_anime_status(mal_id, num_watched=num_watched)
    if result:
        logger.info("ui: episodes watched set to {} for mal_id={}".format(num_watched, mal_id))
        xbmcgui.Dialog().notification("MAL Manager", "Episodes watched: {}".format(num_watched), xbmcgui.NOTIFICATION_INFO, 3000)
    else:
        xbmcgui.Dialog().notification("MAL Manager", "Failed to update episodes", xbmcgui.NOTIFICATION_ERROR, 3000)


def _update_score(mal_id, current_score):
    score_str = xbmcgui.Dialog().input(
        "Enter score (1-10, 0 = no score)",
        str(current_score) if current_score else "0",
        type=xbmcgui.INPUT_NUMERIC
    )
    if score_str is None or score_str == "":
        return
    try:
        score = int(score_str)
        if not (0 <= score <= 10):
            raise ValueError("out of range")
    except ValueError:
        xbmcgui.Dialog().notification("MAL Manager", "Invalid score — must be 0-10", xbmcgui.NOTIFICATION_WARNING, 3000)
        return

    result = mal_api.update_anime_status(mal_id, score=score)
    if result:
        logger.info("ui: score set to {} for mal_id={}".format(score, mal_id))
        xbmcgui.Dialog().notification("MAL Manager", "Score updated: {}".format(score), xbmcgui.NOTIFICATION_INFO, 3000)
    else:
        xbmcgui.Dialog().notification("MAL Manager", "Failed to update score", xbmcgui.NOTIFICATION_ERROR, 3000)


def _change_status(mal_id, current_status):
    statuses = list(mal_api.STATUS_LABELS.items())
    labels = [v for _, v in statuses]
    keys = [k for k, _ in statuses]

    current_idx = keys.index(current_status) if current_status in keys else -1
    choice = xbmcgui.Dialog().select("Select new status", labels, preselect=current_idx)
    if choice < 0:
        return

    new_status = keys[choice]
    _set_status(mal_id, new_status)


def _sync_single_item(mal_id, direction):
    from resources.lib import sync

    xbmcgui.Dialog().notification("MAL Sync", "Syncing…", xbmcgui.NOTIFICATION_INFO, 1500)
    try:
        if direction == "from_mal":
            updated, skipped, errors = sync.sync_single_from_mal(mal_id)
        elif direction == "to_mal":
            updated, skipped, errors = sync.sync_single_to_mal(mal_id)
        else:
            updated, skipped, errors = sync.force_sync_single_from_mal(mal_id)
    except Exception as exc:
        logger.error("ui: single sync exception: {}".format(exc))
        xbmcgui.Dialog().notification("MAL Sync", "Sync failed — check log", xbmcgui.NOTIFICATION_ERROR, 4000)
        return

    if updated > 0:
        xbmc.executebuiltin("UpdateLibrary(video)")

    if updated == 0 and skipped == 0 and errors == 0:
        msg, icon = "Not found in Kodi library", xbmcgui.NOTIFICATION_WARNING
    elif errors:
        msg, icon = "Sync error — check log", xbmcgui.NOTIFICATION_ERROR
    elif updated > 0:
        msg, icon = "Sync complete — updated", xbmcgui.NOTIFICATION_INFO
    else:
        msg, icon = "Already up to date", xbmcgui.NOTIFICATION_INFO

    logger.info("ui: single sync {} for mal_id={} — updated={} skipped={} errors={}".format(
        direction, mal_id, updated, skipped, errors))
    xbmcgui.Dialog().notification("MAL Sync", msg, icon, 3000)


# ── Library sync ──────────────────────────────────────────────────────────────

def show_sync_dialog():
    """Show the MAL ↔ Kodi library sync option dialog."""
    access_token = auth.get_access_token()
    if not access_token:
        go_auth = xbmcgui.Dialog().yesno(
            "MAL Manager",
            "Not authenticated with MyAnimeList.[CR][CR]"
            "If you are already logged into [B]Otaku Testing[/B] with MAL, "
            "re-open this after a moment — credentials are shared automatically.[CR][CR]"
            "Otherwise, press [B]Authorize[/B] to log in now.",
            yeslabel="Authorize",
            nolabel="Cancel"
        )
        if go_auth:
            auth.run_auth_flow()
        return

    options = [
        "Update from MAL  (MAL → Kodi, keep higher local)",
        "Update to MAL  (Kodi → MAL, keep higher MAL)",
        "Complete sync from MAL  (force MAL status onto Kodi)",
    ]
    choice = xbmcgui.Dialog().select("MAL Library Sync", options)

    if choice == 0:
        _run_sync(direction="from_mal")
    elif choice == 1:
        _run_sync(direction="to_mal")
    elif choice == 2:
        _run_sync(direction="force_from_mal")


def _run_sync(direction):
    from resources.lib import sync  # late import to avoid circular dependency

    progress = xbmcgui.DialogProgress()
    titles = {"from_mal": "Update from MAL", "to_mal": "Update to MAL", "force_from_mal": "Complete Sync from MAL"}
    title = titles.get(direction, direction)
    progress.create("MAL Sync — {}".format(title), "Scanning library…")

    def on_progress(current, total, item_title):
        pct = int(current * 100 / total) if total else 0
        progress.update(pct, "Checking: {}".format(item_title))

    def is_cancelled():
        return progress.iscanceled()

    try:
        if direction == "from_mal":
            updated, skipped, errors = sync.sync_from_mal(on_progress, is_cancelled)
        elif direction == "to_mal":
            updated, skipped, errors = sync.sync_to_mal(on_progress, is_cancelled)
        else:
            updated, skipped, errors = sync.force_sync_from_mal(on_progress, is_cancelled)
    except Exception as exc:
        logger.error("ui: sync exception: {}".format(exc))
        progress.close()
        xbmcgui.Dialog().notification("MAL Sync", "Sync failed — check log", xbmcgui.NOTIFICATION_ERROR, 4000)
        return

    progress.close()

    if updated > 0:
        xbmc.executebuiltin("UpdateLibrary(video)")

    msg = "Updated: {}   Skipped: {}".format(updated, skipped)
    if errors:
        msg += "   Errors: {}".format(errors)
    icon = xbmcgui.NOTIFICATION_ERROR if errors else xbmcgui.NOTIFICATION_INFO
    logger.info("ui: sync complete — {}".format(msg))
    xbmcgui.Dialog().notification("MAL Sync", msg, icon, 5000)
