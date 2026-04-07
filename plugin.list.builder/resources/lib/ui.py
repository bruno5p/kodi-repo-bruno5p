"""
Kodi dialog-based management UI for plugin.list.builder.
"""

import os

import xbmcgui
import xbmcaddon

from resources.lib.logger import logger
from resources.lib import list_manager, list_builder, smartplaylist_reader
from resources.lib.genres import (
    get_genre_map, ids_to_names,
    SORT_OPTIONS, LANGUAGE_OPTIONS, COUNTRY_OPTIONS,
    INTERVAL_OPTIONS, MEDIATYPE_OPTIONS,
)
from resources.lib.smartplaylist_reader import SAMPLER_SORT_OPTIONS

ADDON = xbmcaddon.Addon()

_ADDON_NAME = "List Builder"


def _get_api_key():
    return ADDON.getSetting("tmdb_api_key").strip()


# ---------------------------------------------------------------------------
# Main management screen
# ---------------------------------------------------------------------------

def show_management():
    """
    Main management screen. Shows all configured lists with per-list actions.
    Loops until the user cancels.
    """
    while True:
        lists = list_manager.load_lists()

        menu_items = ["[COLOR yellow]+ Add new list[/COLOR]"]
        for entry in lists:
            if entry.get("type") == "smartplaylist":
                playlist_name = os.path.basename(entry.get("playlist_path", "")).replace(".xsp", "")
                menu_items.append("{} [COLOR gray](sampler: {})[/COLOR]".format(
                    entry["label"], playlist_name
                ))
            elif entry.get("type") == "mdblist":
                last = entry.get("last_updated") or "never"
                menu_items.append("{} [COLOR gray](mdblist, updated: {})[/COLOR]".format(
                    entry["label"], last
                ))
            else:
                last = entry.get("last_updated") or "never"
                menu_items.append("{} [COLOR gray]({}, updated: {})[/COLOR]".format(
                    entry["label"], entry.get("mediatype", ""), last
                ))

        choice = xbmcgui.Dialog().select("{} Manager".format(_ADDON_NAME), menu_items)
        if choice < 0:
            return

        if choice == 0:
            new_entry = show_add_list()
            if new_entry:
                _offer_immediate_build(new_entry)
        else:
            entry = lists[choice - 1]
            _show_list_actions(entry)


def _show_list_actions(entry):
    if entry.get("type") == "smartplaylist":
        actions = ["Edit", "Delete"]
        choice = xbmcgui.Dialog().select(entry["label"], actions)
        if choice == 0:
            show_edit_smartplaylist(entry)
        elif choice == 1:
            _confirm_delete(entry)
    elif entry.get("type") == "mdblist":
        actions = ["Update now", "Edit", "Show widget URL", "Delete"]
        choice = xbmcgui.Dialog().select(entry["label"], actions)
        if choice == 0:
            _run_update(entry)
        elif choice == 1:
            show_edit_mdblist(entry)
        elif choice == 2:
            show_widget_url(entry)
        elif choice == 3:
            _confirm_delete(entry)
    else:
        actions = ["Update now", "Edit", "Show widget URL", "Delete"]
        choice = xbmcgui.Dialog().select(entry["label"], actions)
        if choice == 0:
            _run_update(entry)
        elif choice == 1:
            show_edit_list(entry)
        elif choice == 2:
            show_widget_url(entry)
        elif choice == 3:
            _confirm_delete(entry)


def _offer_immediate_build(entry):
    if entry.get("type") == "smartplaylist":
        return  # dynamic — no build step needed

    do_build = xbmcgui.Dialog().yesno(
        _ADDON_NAME,
        "List '{}' created.[CR]Fetch items now?".format(entry["label"]),
        yeslabel="Yes, fetch",
        nolabel="Later",
    )
    if do_build:
        _run_update(entry)
    else:
        show_widget_url(entry)


def _run_update(entry):
    entry_type = entry.get("type", "tmdb")
    if entry_type == "tmdb":
        api_key = _get_api_key()
        if not api_key:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, "No TMDb API key configured!",
                xbmcgui.NOTIFICATION_ERROR, 4000,
            )
            return
    else:
        api_key = None

    xbmcgui.Dialog().notification(
        _ADDON_NAME, "Updating: {}".format(entry["label"]),
        xbmcgui.NOTIFICATION_INFO, 2000,
    )
    success = list_builder.build_entry(entry, api_key)
    if success:
        list_manager.mark_updated(entry["id"])
        xbmcgui.Dialog().notification(
            _ADDON_NAME, "'{}' updated.".format(entry["label"]),
            xbmcgui.NOTIFICATION_INFO, 3000,
        )
        updated_lists = list_manager.load_lists()
        updated_entry = next((e for e in updated_lists if e["id"] == entry["id"]), entry)
        show_widget_url(updated_entry)
    else:
        xbmcgui.Dialog().notification(
            _ADDON_NAME, "Failed to update '{}'.".format(entry["label"]),
            xbmcgui.NOTIFICATION_ERROR, 4000,
        )


def _confirm_delete(entry):
    confirmed = xbmcgui.Dialog().yesno(
        "Delete list",
        "Delete '{}'?[CR][COLOR red]This also removes the items file.[/COLOR]".format(entry["label"]),
        yeslabel="Delete",
        nolabel="Cancel",
    )
    if confirmed:
        list_manager.delete_list(entry["id"])
        xbmcgui.Dialog().notification(
            _ADDON_NAME, "Deleted: {}".format(entry["label"]),
            xbmcgui.NOTIFICATION_INFO, 2000,
        )


def show_widget_url(entry):
    """
    Display the mdblist_locallist URL so the user can copy it into a skin widget.
    Uses a pre-filled text input for easy select-all copy.
    """
    url = list_manager.get_widget_url(entry)
    logger.info("ui: widget URL for '{}': {}".format(entry["label"], url))
    xbmcgui.Dialog().input(
        "Widget URL for: {}".format(entry["label"]),
        defaultt=url,
        type=xbmcgui.INPUT_ALPHANUM,
    )


# ---------------------------------------------------------------------------
# Add list — choose source type, then branch
# ---------------------------------------------------------------------------

def show_add_list():
    """
    Ask the user which kind of list to create, then branch to the appropriate flow.
    Returns the new list entry dict on success, or None if cancelled.
    """
    d = xbmcgui.Dialog()
    source_choice = d.select("List type", ["TMDb Discover", "Smart Playlist Sampler", "MDBList"])
    if source_choice < 0:
        return None
    if source_choice == 1:
        return show_add_smartplaylist()
    if source_choice == 2:
        return _show_add_mdblist()
    return _show_add_tmdb_list()


# ---------------------------------------------------------------------------
# Add TMDb list — sequential dialogs (existing flow)
# ---------------------------------------------------------------------------

def _show_add_tmdb_list():
    """
    Multi-step dialog to create a new TMDb Discover list config.
    Returns the new list entry dict on success, or None if cancelled.
    """
    d = xbmcgui.Dialog()

    label = d.input("List name", defaultt="", type=xbmcgui.INPUT_ALPHANUM)
    if not label:
        return None

    description = d.input("Description (optional)", defaultt="", type=xbmcgui.INPUT_ALPHANUM)

    mt_choice = d.select("Media type", [o[0] for o in MEDIATYPE_OPTIONS])
    if mt_choice < 0:
        return None
    mediatype = MEDIATYPE_OPTIONS[mt_choice][1]

    lang_choice = d.select("Original language", [o[0] for o in LANGUAGE_OPTIONS])
    if lang_choice < 0:
        return None
    language = LANGUAGE_OPTIONS[lang_choice][1]

    country_choice = d.select("Origin country", [o[0] for o in COUNTRY_OPTIONS])
    if country_choice < 0:
        return None
    country = COUNTRY_OPTIONS[country_choice][1]

    result = _select_genres(d, mediatype, "Include genres")
    with_genres = result if result is not None else []
    result = _select_genres(d, mediatype, "Exclude genres")
    without_genres = result if result is not None else []

    sort_choice = d.select("Sort by", [o[0] for o in SORT_OPTIONS])
    if sort_choice < 0:
        return None
    sort_by = SORT_OPTIONS[sort_choice][1]

    year_filter_type = d.select("Year filter", [
        "No year filter",
        "Released since fixed date (e.g. 1991-01-01)",
        "Released in last N days (dynamic)",
    ])
    first_air_date_gte = None
    first_air_date_gte_days = None
    if year_filter_type == 1:
        date_str = d.input("Start date (YYYY-MM-DD)", defaultt="1991-01-01", type=xbmcgui.INPUT_ALPHANUM)
        if date_str:
            first_air_date_gte = date_str
    elif year_filter_type == 2:
        days_str = d.input("Number of days", defaultt="365", type=xbmcgui.INPUT_NUMERIC)
        if days_str:
            try:
                first_air_date_gte_days = int(days_str)
            except ValueError:
                pass

    vote_count_gte = None  # default: no minimum — editable later
    vote_average_lte = None  # default: no max rating — editable later
    total_items = 100  # default: 100 items — editable later

    vote_avg_gte_str = d.input("Min rating 0-10 (0 = none)", defaultt="0", type=xbmcgui.INPUT_NUMERIC)
    try:
        vote_average_gte = float(vote_avg_gte_str) if vote_avg_gte_str and float(vote_avg_gte_str) > 0 else None
    except ValueError:
        vote_average_gte = None

    interval_choice = d.select("Update interval", [o[0] for o in INTERVAL_OPTIONS], preselect=3)
    if interval_choice < 0:
        return None
    update_interval = INTERVAL_OPTIONS[interval_choice][1]

    filters = {
        "with_original_language": language,
        "with_origin_country": country,
        "with_genres": with_genres,
        "without_genres": without_genres,
        "sort_by": sort_by,
        "first_air_date_gte": first_air_date_gte,
        "first_air_date_gte_days": first_air_date_gte_days,
        "vote_count_gte": vote_count_gte,
        "vote_average_gte": vote_average_gte,
        "vote_average_lte": vote_average_lte,
        "total_items": total_items,
    }

    return list_manager.add_list(
        label=label,
        description=description,
        list_type="tmdb",
        mediatype=mediatype,
        update_interval=update_interval,
        filters=filters,
    )


def _select_genres(dialog, mediatype, prompt, preselected_ids=None):
    """
    Multi-select for genres using the native multiselect dialog (no refresh loop).
    Returns selected genre ID list, or None if the dialog was cancelled.
    """
    genre_map = get_genre_map(mediatype)
    genre_names = sorted(genre_map.keys())

    preselect = [i for i, name in enumerate(genre_names)
                 if genre_map[name] in (preselected_ids or [])]

    result = dialog.multiselect(prompt, genre_names, preselect=preselect)
    if result is None:
        return None  # user pressed Back — caller decides what to do

    return [genre_map[genre_names[i]] for i in result]


# ---------------------------------------------------------------------------
# Add / Edit MDBList
# ---------------------------------------------------------------------------

def _show_add_mdblist():
    """
    Multi-step dialog to create a new MDBList entry.
    Returns the new list entry dict on success, or None if cancelled.
    """
    d = xbmcgui.Dialog()

    label = d.input("List name", defaultt="", type=xbmcgui.INPUT_ALPHANUM)
    if not label:
        return None

    url = d.input(
        "MDBList URL (e.g. https://mdblist.com/lists/user/listname)",
        defaultt="https://mdblist.com/lists/",
        type=xbmcgui.INPUT_ALPHANUM,
    )
    if not url or url == "https://mdblist.com/lists/":
        return None

    total_str = d.input("Max items to fetch", defaultt="50", type=xbmcgui.INPUT_NUMERIC)
    try:
        total_items = int(total_str) if total_str and int(total_str) > 0 else 50
    except ValueError:
        total_items = 50

    interval_choice = d.select("Update interval", [o[0] for o in INTERVAL_OPTIONS], preselect=3)
    if interval_choice < 0:
        return None
    update_interval = INTERVAL_OPTIONS[interval_choice][1]

    return list_manager.add_list(
        label=label,
        description="",
        list_type="mdblist",
        update_interval=update_interval,
        mdblist_config={"mdblist_url": url, "total_items": total_items},
    )


def show_edit_mdblist(entry):
    """
    Menu-based edit dialog for MDBList entries.
    Returns True if changes were saved.
    """
    working = {
        "label": entry["label"],
        "mdblist_url": entry.get("mdblist_url", ""),
        "total_items": entry.get("total_items", 50),
        "update_interval": entry.get("update_interval", 1),
    }

    changed = False

    while True:
        menu_items = [
            "Name:             {}".format(working["label"]),
            "MDBList URL:      {}".format(working["mdblist_url"] or "(not set)"),
            "Max items:        {}".format(working["total_items"]),
            "Update interval:  {} days".format(working["update_interval"]),
            "[COLOR green]Save[/COLOR]",
            "[COLOR red]Cancel[/COLOR]",
        ]

        choice = xbmcgui.Dialog().select("Edit: {}".format(working["label"]), menu_items)

        SAVE_IDX = len(menu_items) - 2
        CANCEL_IDX = len(menu_items) - 1

        if choice < 0 or choice == CANCEL_IDX:
            break

        if choice == SAVE_IDX:
            list_manager.update_list(entry["id"], {
                "label": working["label"],
                "mdblist_url": working["mdblist_url"],
                "total_items": working["total_items"],
                "update_interval": working["update_interval"],
            })
            changed = True
            xbmcgui.Dialog().notification(
                _ADDON_NAME, "'{}' saved.".format(working["label"]),
                xbmcgui.NOTIFICATION_INFO, 2000,
            )
            break

        d = xbmcgui.Dialog()

        if choice == 0:
            val = d.input("List name", defaultt=working["label"], type=xbmcgui.INPUT_ALPHANUM)
            if val:
                working["label"] = val

        elif choice == 1:
            val = d.input("MDBList URL", defaultt=working["mdblist_url"], type=xbmcgui.INPUT_ALPHANUM)
            if val:
                working["mdblist_url"] = val

        elif choice == 2:
            val = d.input("Max items to fetch",
                          defaultt=str(working["total_items"]),
                          type=xbmcgui.INPUT_NUMERIC)
            try:
                if val and int(val) > 0:
                    working["total_items"] = int(val)
            except ValueError:
                pass

        elif choice == 3:
            keys = [o[1] for o in INTERVAL_OPTIONS]
            cur = working["update_interval"]
            cur_idx = keys.index(cur) if cur in keys else 3
            c = d.select("Update interval", [o[0] for o in INTERVAL_OPTIONS], preselect=cur_idx)
            if c >= 0:
                working["update_interval"] = keys[c]

    return changed


# ---------------------------------------------------------------------------
# Add Smart Playlist Sampler
# ---------------------------------------------------------------------------

def show_add_smartplaylist():
    """
    Multi-step dialog to create a Smart Playlist Sampler entry.
    Returns the new list entry dict on success, or None if cancelled.
    """
    d = xbmcgui.Dialog()

    label = d.input("Sampler name", defaultt="", type=xbmcgui.INPUT_ALPHANUM)
    if not label:
        return None

    playlists = smartplaylist_reader.list_smartplaylists()
    if not playlists:
        d.notification(
            _ADDON_NAME,
            "No smart playlists found in special://userdata/playlists/video/",
            xbmcgui.NOTIFICATION_ERROR, 4000,
        )
        return None

    pl_names = [p[0] for p in playlists]
    pl_choice = d.select("Select smart playlist", pl_names)
    if pl_choice < 0:
        return None
    playlist_path = playlists[pl_choice][1]

    size_str = d.input("Sample size", defaultt="20", type=xbmcgui.INPUT_NUMERIC)
    try:
        sample_size = int(size_str) if size_str and int(size_str) > 0 else 20
    except ValueError:
        sample_size = 20

    sort_choice = d.select("Sort by", [o[0] for o in SAMPLER_SORT_OPTIONS])
    if sort_choice < 0:
        return None
    sort_by = SAMPLER_SORT_OPTIONS[sort_choice][1]

    sort_direction = "ascending"
    if sort_by != "random":
        dir_choice = d.select("Order", ["Ascending", "Descending"])
        if dir_choice < 0:
            return None
        sort_direction = "descending" if dir_choice == 1 else "ascending"

    return list_manager.add_list(
        label=label,
        description="",
        list_type="smartplaylist",
        playlist_config={
            "playlist_path": playlist_path,
            "sample_size": sample_size,
            "sort_by": sort_by,
            "sort_direction": sort_direction,
        },
    )


# ---------------------------------------------------------------------------
# Edit list — TMDb: menu-based, each field selectable
# ---------------------------------------------------------------------------

def show_edit_list(entry):
    """
    Menu-based edit dialog for TMDb Discover lists. Each field is shown with its
    current value and can be selected to change. Save/Cancel at the bottom.
    Returns True if changes were saved.
    """
    working = {
        "label": entry["label"],
        "description": entry.get("description", ""),
        "mediatype": entry.get("mediatype", "show"),
        "update_interval": entry.get("update_interval", 30),
        "filters": {k: list(v) if isinstance(v, list) else v
                    for k, v in entry.get("filters", {}).items()},
    }

    changed = False

    while True:
        f = working["filters"]
        with_names = ids_to_names(f.get("with_genres") or [], working["mediatype"])
        without_names = ids_to_names(f.get("without_genres") or [], working["mediatype"])

        menu_items = [
            "Name:             {}".format(working["label"]),
            "Description:      {}".format(working.get("description") or "(none)"),
            "Media type:       {}".format(working["mediatype"]),
            "Language:         {}".format(f.get("with_original_language") or "(any)"),
            "Country:          {}".format(f.get("with_origin_country") or "(any)"),
            "Include genres:   {}".format(", ".join(with_names) if with_names else "(any)"),
            "Exclude genres:   {}".format(", ".join(without_names) if without_names else "(none)"),
            "Sort by:          {}".format(f.get("sort_by") or "(default)"),
            "Year filter:      {}".format(_describe_year_filter(f)),
            "Min votes:        {}".format(f.get("vote_count_gte") or "(none)"),
            "Min rating:       {}".format(f.get("vote_average_gte") or "(none)"),
            "Max rating:       {}".format(f.get("vote_average_lte") or "(none)"),
            "Items to fetch:   {}".format(f.get("total_items", 80)),
            "Update interval:  {} days".format(working["update_interval"]),
            "[COLOR green]Save[/COLOR]",
            "[COLOR red]Cancel[/COLOR]",
        ]

        choice = xbmcgui.Dialog().select("Edit: {}".format(working["label"]), menu_items)

        SAVE_IDX = len(menu_items) - 2
        CANCEL_IDX = len(menu_items) - 1

        if choice < 0 or choice == CANCEL_IDX:
            break

        if choice == SAVE_IDX:
            list_manager.update_list(entry["id"], {
                "label": working["label"],
                "description": working["description"],
                "mediatype": working["mediatype"],
                "update_interval": working["update_interval"],
                "filters": working["filters"],
            })
            changed = True
            xbmcgui.Dialog().notification(
                _ADDON_NAME, "'{}' saved.".format(working["label"]),
                xbmcgui.NOTIFICATION_INFO, 2000,
            )
            break

        d = xbmcgui.Dialog()

        if choice == 0:
            val = d.input("List name", defaultt=working["label"], type=xbmcgui.INPUT_ALPHANUM)
            if val:
                working["label"] = val

        elif choice == 1:
            val = d.input("Description", defaultt=working.get("description", ""), type=xbmcgui.INPUT_ALPHANUM)
            working["description"] = val

        elif choice == 2:
            keys = [o[1] for o in MEDIATYPE_OPTIONS]
            cur_idx = keys.index(working["mediatype"]) if working["mediatype"] in keys else 0
            c = d.select("Media type", [o[0] for o in MEDIATYPE_OPTIONS], preselect=cur_idx)
            if c >= 0:
                working["mediatype"] = keys[c]
                working["filters"]["with_genres"] = []
                working["filters"]["without_genres"] = []

        elif choice == 3:
            keys = [o[1] for o in LANGUAGE_OPTIONS]
            cur = f.get("with_original_language")
            cur_idx = keys.index(cur) if cur in keys else 0
            c = d.select("Original language", [o[0] for o in LANGUAGE_OPTIONS], preselect=cur_idx)
            if c >= 0:
                working["filters"]["with_original_language"] = keys[c]

        elif choice == 4:
            keys = [o[1] for o in COUNTRY_OPTIONS]
            cur = f.get("with_origin_country")
            cur_idx = keys.index(cur) if cur in keys else 0
            c = d.select("Origin country", [o[0] for o in COUNTRY_OPTIONS], preselect=cur_idx)
            if c >= 0:
                working["filters"]["with_origin_country"] = keys[c]

        elif choice == 5:
            result = _select_genres(
                d, working["mediatype"], "Include genres",
                working["filters"].get("with_genres"),
            )
            if result is not None:
                working["filters"]["with_genres"] = result

        elif choice == 6:
            result = _select_genres(
                d, working["mediatype"], "Exclude genres",
                working["filters"].get("without_genres"),
            )
            if result is not None:
                working["filters"]["without_genres"] = result

        elif choice == 7:
            keys = [o[1] for o in SORT_OPTIONS]
            cur = f.get("sort_by")
            cur_idx = keys.index(cur) if cur in keys else 0
            c = d.select("Sort by", [o[0] for o in SORT_OPTIONS], preselect=cur_idx)
            if c >= 0:
                working["filters"]["sort_by"] = keys[c]

        elif choice == 8:
            _edit_year_filter(d, working["filters"])

        elif choice == 9:
            val = d.input("Min vote count (0 = none)",
                          defaultt=str(f.get("vote_count_gte") or 0),
                          type=xbmcgui.INPUT_NUMERIC)
            try:
                working["filters"]["vote_count_gte"] = int(val) if val and int(val) > 0 else None
            except ValueError:
                pass

        elif choice == 10:
            val = d.input("Min rating 0-10 (0 = none)",
                          defaultt=str(f.get("vote_average_gte") or 0),
                          type=xbmcgui.INPUT_NUMERIC)
            try:
                working["filters"]["vote_average_gte"] = float(val) if val and float(val) > 0 else None
            except ValueError:
                pass

        elif choice == 11:
            val = d.input("Max rating 0-10 (0 = none)",
                          defaultt=str(f.get("vote_average_lte") or 0),
                          type=xbmcgui.INPUT_NUMERIC)
            try:
                working["filters"]["vote_average_lte"] = float(val) if val and float(val) > 0 else None
            except ValueError:
                pass

        elif choice == 12:
            val = d.input("Items to fetch",
                          defaultt=str(f.get("total_items", 80)),
                          type=xbmcgui.INPUT_NUMERIC)
            try:
                if val:
                    working["filters"]["total_items"] = int(val)
            except ValueError:
                pass

        elif choice == 13:
            keys = [o[1] for o in INTERVAL_OPTIONS]
            cur = working["update_interval"]
            cur_idx = keys.index(cur) if cur in keys else 3
            c = d.select("Update interval", [o[0] for o in INTERVAL_OPTIONS], preselect=cur_idx)
            if c >= 0:
                working["update_interval"] = keys[c]

    return changed


def _describe_year_filter(filters):
    static = filters.get("first_air_date_gte")
    dynamic = filters.get("first_air_date_gte_days")
    if static:
        return "since {}".format(static)
    if dynamic is not None:
        return "last {} days".format(dynamic)
    return "(none)"


def _edit_year_filter(dialog, filters):
    choice = dialog.select("Year filter", [
        "Clear year filter",
        "Fixed date (YYYY-MM-DD)",
        "Last N days (dynamic)",
    ])
    if choice == 0:
        filters["first_air_date_gte"] = None
        filters["first_air_date_gte_days"] = None
    elif choice == 1:
        current = filters.get("first_air_date_gte") or "1991-01-01"
        val = dialog.input("Start date (YYYY-MM-DD)", defaultt=current, type=xbmcgui.INPUT_ALPHANUM)
        if val:
            filters["first_air_date_gte"] = val
            filters["first_air_date_gte_days"] = None
    elif choice == 2:
        current = str(filters.get("first_air_date_gte_days") or 365)
        val = dialog.input("Number of days", defaultt=current, type=xbmcgui.INPUT_NUMERIC)
        try:
            if val:
                filters["first_air_date_gte_days"] = int(val)
                filters["first_air_date_gte"] = None
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Edit Smart Playlist Sampler
# ---------------------------------------------------------------------------

def show_edit_smartplaylist(entry):
    """
    Menu-based edit dialog for Smart Playlist Sampler entries.
    Returns True if changes were saved.
    """
    sort_keys = [o[1] for o in SAMPLER_SORT_OPTIONS]

    working = {
        "label": entry["label"],
        "playlist_path": entry.get("playlist_path", ""),
        "sample_size": entry.get("sample_size", 20),
        "sort_by": entry.get("sort_by", "random"),
        "sort_direction": entry.get("sort_direction", "ascending"),
    }

    changed = False

    while True:
        playlist_name = os.path.basename(working["playlist_path"]).replace(".xsp", "") or "(none)"
        sort_label = next((o[0] for o in SAMPLER_SORT_OPTIONS if o[1] == working["sort_by"]), working["sort_by"])

        menu_items = [
            "Name:           {}".format(working["label"]),
            "Playlist:       {}".format(playlist_name),
            "Sample size:    {}".format(working["sample_size"]),
            "Sort by:        {}".format(sort_label),
            "Order:          {}".format(working["sort_direction"]),
            "[COLOR green]Save[/COLOR]",
            "[COLOR red]Cancel[/COLOR]",
        ]

        choice = xbmcgui.Dialog().select("Edit sampler: {}".format(working["label"]), menu_items)

        SAVE_IDX = len(menu_items) - 2
        CANCEL_IDX = len(menu_items) - 1

        if choice < 0 or choice == CANCEL_IDX:
            break

        if choice == SAVE_IDX:
            list_manager.update_list(entry["id"], {
                "label": working["label"],
                "playlist_path": working["playlist_path"],
                "sample_size": working["sample_size"],
                "sort_by": working["sort_by"],
                "sort_direction": working["sort_direction"],
            })
            changed = True
            xbmcgui.Dialog().notification(
                _ADDON_NAME, "'{}' saved.".format(working["label"]),
                xbmcgui.NOTIFICATION_INFO, 2000,
            )
            break

        d = xbmcgui.Dialog()

        if choice == 0:
            val = d.input("Sampler name", defaultt=working["label"], type=xbmcgui.INPUT_ALPHANUM)
            if val:
                working["label"] = val

        elif choice == 1:
            playlists = smartplaylist_reader.list_smartplaylists()
            if playlists:
                pl_names = [p[0] for p in playlists]
                cur_paths = [p[1] for p in playlists]
                cur_idx = cur_paths.index(working["playlist_path"]) if working["playlist_path"] in cur_paths else 0
                c = d.select("Select smart playlist", pl_names, preselect=cur_idx)
                if c >= 0:
                    working["playlist_path"] = playlists[c][1]

        elif choice == 2:
            val = d.input("Sample size", defaultt=str(working["sample_size"]), type=xbmcgui.INPUT_NUMERIC)
            try:
                if val and int(val) > 0:
                    working["sample_size"] = int(val)
            except ValueError:
                pass

        elif choice == 3:
            cur_idx = sort_keys.index(working["sort_by"]) if working["sort_by"] in sort_keys else 0
            c = d.select("Sort by", [o[0] for o in SAMPLER_SORT_OPTIONS], preselect=cur_idx)
            if c >= 0:
                working["sort_by"] = SAMPLER_SORT_OPTIONS[c][1]

        elif choice == 4:
            if working["sort_by"] == "random":
                d.notification(_ADDON_NAME, "Order is not used with Random sort.",
                               xbmcgui.NOTIFICATION_INFO, 2000)
            else:
                dirs = ["ascending", "descending"]
                cur_idx = dirs.index(working["sort_direction"]) if working["sort_direction"] in dirs else 0
                c = d.select("Order", ["Ascending", "Descending"], preselect=cur_idx)
                if c >= 0:
                    working["sort_direction"] = dirs[c]

    return changed
