"""
Kodi dialog-based management UI for script.tmdb.lists.
"""

import xbmcgui
import xbmcaddon

from resources.lib.logger import logger
from resources.lib import list_manager, list_builder
from resources.lib.genres import (
    get_genre_map, ids_to_names,
    SORT_OPTIONS, LANGUAGE_OPTIONS, COUNTRY_OPTIONS,
    INTERVAL_OPTIONS, MEDIATYPE_OPTIONS,
)

ADDON = xbmcaddon.Addon()


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
            last = entry.get("last_updated") or "never"
            menu_items.append("{} [COLOR gray]({}, updated: {})[/COLOR]".format(
                entry["label"], entry["mediatype"], last
            ))

        choice = xbmcgui.Dialog().select("TMDb Lists Manager", menu_items)
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
    do_build = xbmcgui.Dialog().yesno(
        "TMDb Lists",
        "List '{}' created.[CR]Fetch items now?".format(entry["label"]),
        yeslabel="Yes, fetch",
        nolabel="Later",
    )
    if do_build:
        _run_update(entry)
    else:
        show_widget_url(entry)


def _run_update(entry):
    api_key = _get_api_key()
    if not api_key:
        xbmcgui.Dialog().notification(
            "TMDb Lists", "No TMDb API key configured!",
            xbmcgui.NOTIFICATION_ERROR, 4000,
        )
        return

    xbmcgui.Dialog().notification(
        "TMDb Lists", "Updating: {}".format(entry["label"]),
        xbmcgui.NOTIFICATION_INFO, 2000,
    )
    success = list_builder.build_list(entry, api_key)
    if success:
        list_manager.mark_updated(entry["id"])
        xbmcgui.Dialog().notification(
            "TMDb Lists", "'{}' updated.".format(entry["label"]),
            xbmcgui.NOTIFICATION_INFO, 3000,
        )
        updated_lists = list_manager.load_lists()
        updated_entry = next((e for e in updated_lists if e["id"] == entry["id"]), entry)
        show_widget_url(updated_entry)
    else:
        xbmcgui.Dialog().notification(
            "TMDb Lists", "Failed to update '{}'.".format(entry["label"]),
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
            "TMDb Lists", "Deleted: {}".format(entry["label"]),
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
# Add list — sequential dialogs
# ---------------------------------------------------------------------------

def show_add_list():
    """
    Multi-step dialog to create a new list config.
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
# Edit list — menu-based, each field selectable
# ---------------------------------------------------------------------------

def show_edit_list(entry):
    """
    Menu-based edit dialog. Each field is shown with its current value and
    can be selected to change. Save/Cancel at the bottom.
    Returns True if changes were saved.
    """
    working = {
        "label": entry["label"],
        "description": entry.get("description", ""),
        "mediatype": entry["mediatype"],
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
                "TMDb Lists", "'{}' saved.".format(working["label"]),
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
