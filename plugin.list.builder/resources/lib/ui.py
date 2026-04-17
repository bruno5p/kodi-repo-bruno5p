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
from resources.lib.mdblist_api import (
    MDBLIST_SORT_OPTIONS, MDBLIST_MEDIATYPE_OPTIONS,
    MDBLIST_GENRES, MDBLIST_APPEND_OPTIONS,
)
from resources.lib.smartplaylist_reader import SAMPLER_SORT_OPTIONS

ADDON = xbmcaddon.Addon()

_ADDON_NAME = "List Builder"

_DATE_MODE_OPTIONS = [
    ("No date filter",             ""),
    ("Static date (YYYY-MM-DD)",   "static"),
    ("Last N months (dynamic)",    "last_months"),
    ("Last N years (dynamic)",     "last_years"),
]
_DATE_MODE_KEYS = [o[1] for o in _DATE_MODE_OPTIONS]


def _ask_date_filter(d, prompt, current_mode, current_static, current_n):
    """
    Two-step dialog: pick mode, then enter value if needed.
    Returns (mode, static_date, n).
    Cancelled sub-dialog keeps the current value unchanged.
    """
    preselect = _DATE_MODE_KEYS.index(current_mode) if current_mode in _DATE_MODE_KEYS else 0
    choice = d.select(prompt, [o[0] for o in _DATE_MODE_OPTIONS], preselect=preselect)
    if choice < 0:
        return current_mode, current_static, current_n  # cancelled — keep as-is

    mode = _DATE_MODE_KEYS[choice]
    static_date = current_static
    n = current_n

    if mode == "static":
        val = d.input("Date (YYYY-MM-DD)", defaultt=current_static or "", type=xbmcgui.INPUT_ALPHANUM)
        static_date = val.strip() if val else ""
    elif mode in ("last_months", "last_years"):
        unit = "months" if mode == "last_months" else "years"
        val = d.input("Number of {}".format(unit), defaultt=str(current_n or 12), type=xbmcgui.INPUT_NUMERIC)
        try:
            n = int(val) if val and int(val) > 0 else (current_n or 12)
        except ValueError:
            n = current_n or 12

    return mode, static_date, n


def _date_filter_label(mode, static_date, n):
    """Human-readable summary of a date filter for menu display."""
    if mode == "static":
        return static_date or "(any)"
    if mode == "last_months":
        return "Last {} month{}".format(n, "s" if n != 1 else "")
    if mode == "last_years":
        return "Last {} year{}".format(n, "s" if n != 1 else "")
    return "(any)"


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
        lists = sorted(list_manager.load_lists(), key=lambda e: e.get("label", "").lower())

        menu_items = ["[COLOR yellow]+ Add new list[/COLOR]"]
        for entry in lists:
            if entry.get("type") == "smartplaylist":
                playlist_name = os.path.basename(entry.get("playlist_path", "")).replace(".xsp", "")
                menu_items.append("{} [COLOR gray](sampler: {})[/COLOR]".format(
                    entry["label"], playlist_name
                ))
            elif entry.get("type") == "local_otaku_recent":
                menu_items.append("{} [COLOR gray](local + otaku recent)[/COLOR]".format(entry["label"]))
            elif entry.get("type") == "local_fen_recent_movies":
                menu_items.append("{} [COLOR gray](local + fen movies)[/COLOR]".format(entry["label"]))
            elif entry.get("type") == "local_fen_recent_series":
                menu_items.append("{} [COLOR gray](local + fen series)[/COLOR]".format(entry["label"]))
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
    elif entry.get("type") == "local_otaku_recent":
        actions = ["Rename", "Show widget URL", "Delete"]
        choice = xbmcgui.Dialog().select(entry["label"], actions)
        if choice == 0:
            _show_rename_local_otaku_recent(entry)
        elif choice == 1:
            show_widget_url(entry)
        elif choice == 2:
            _confirm_delete(entry)
    elif entry.get("type") in ("local_fen_recent_movies", "local_fen_recent_series"):
        actions = ["Rename", "Show widget URL", "Delete"]
        choice = xbmcgui.Dialog().select(entry["label"], actions)
        if choice == 0:
            _show_rename_local_fen_recent(entry)
        elif choice == 1:
            show_widget_url(entry)
        elif choice == 2:
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
    if entry.get("type") in ("smartplaylist", "local_otaku_recent", "local_fen_recent_movies", "local_fen_recent_series"):
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
    elif entry_type == "mdblist":
        mdb_key = ADDON.getSetting("mdblist_api_key").strip()
        if not mdb_key:
            xbmcgui.Dialog().notification(
                _ADDON_NAME, "No MDBList API key configured!",
                xbmcgui.NOTIFICATION_ERROR, 4000,
            )
            return
        api_key = None
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
    source_choice = d.select("List type", [
        "TMDb Discover", "Smart Playlist Sampler", "MDBList",
        "Local + Otaku Recently Watched",
        "Local + Fen Recently Watched Movies",
        "Local + Fen Recently Watched Series",
    ])
    if source_choice < 0:
        return None
    if source_choice == 1:
        return show_add_smartplaylist()
    if source_choice == 2:
        return _show_add_mdblist()
    if source_choice == 3:
        return _show_add_local_otaku_recent()
    if source_choice == 4:
        return _show_add_local_fen_recent("movies")
    if source_choice == 5:
        return _show_add_local_fen_recent("series")
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

    # --- API filters (ignored when no MDBList API key is configured) ---

    sort_labels = ["(default / no sort)"] + [o[0] for o in MDBLIST_SORT_OPTIONS]
    sort_keys   = [""]                    + [o[1] for o in MDBLIST_SORT_OPTIONS]
    sort_choice = d.select("Sort by (API only)", sort_labels)
    if sort_choice < 0:
        sort_choice = 0  # treat cancel as "no sort"
    sort = sort_keys[sort_choice]

    order = ""
    if sort:
        order_choice = d.select("Sort order (API only)", ["Ascending", "Descending"])
        if order_choice < 0:
            order_choice = 0
        order = "desc" if order_choice == 1 else "asc"

    mt_choice = d.select(
        "Media type filter (API only)",
        [o[0] for o in MDBLIST_MEDIATYPE_OPTIONS],
    )
    mediatype = "" if mt_choice < 0 else MDBLIST_MEDIATYPE_OPTIONS[mt_choice][1]

    inc_result = d.multiselect(
        "Genres to include (API only — none selected = any)",
        MDBLIST_GENRES,
        preselect=[],
    )
    genres_include = [MDBLIST_GENRES[i] for i in (inc_result or [])]

    _anime_idx = MDBLIST_GENRES.index("Anime") if "Anime" in MDBLIST_GENRES else -1
    exc_result = d.multiselect(
        "Genres to exclude (API only — exclude wins on conflict)",
        MDBLIST_GENRES,
        preselect=[_anime_idx] if _anime_idx >= 0 else [],
    )
    genres_exclude = [MDBLIST_GENRES[i] for i in (exc_result or [])]

    # Client-side priority: exclude wins
    genres_include = [g for g in genres_include if g not in genres_exclude]

    rf_mode, rf_static, rf_n = _ask_date_filter(d, "Released from (API only)", "", "", 12)
    rt_mode, rt_static, rt_n = _ask_date_filter(d, "Released to (API only)", "", "", 12)

    append_keys = [o[1] for o in MDBLIST_APPEND_OPTIONS]
    preselect_ratings = [i for i, o in enumerate(MDBLIST_APPEND_OPTIONS) if o[1] == "ratings"]
    append_result = d.multiselect(
        "Append to response (API only)",
        [o[0] for o in MDBLIST_APPEND_OPTIONS],
        preselect=preselect_ratings,
    )
    append_to_response = ",".join(append_keys[i] for i in (append_result or []))

    interval_choice = d.select("Update interval", [o[0] for o in INTERVAL_OPTIONS], preselect=3)
    if interval_choice < 0:
        return None
    update_interval = INTERVAL_OPTIONS[interval_choice][1]

    mdblist_filters = {
        "sort": sort,
        "order": order,
        "mediatype": mediatype,
        "genres_include": genres_include,
        "genres_exclude": genres_exclude,
        "released_from": rf_static,
        "released_from_mode": rf_mode,
        "released_from_n": rf_n,
        "released_to": rt_static,
        "released_to_mode": rt_mode,
        "released_to_n": rt_n,
        "append_to_response": append_to_response,
    }

    return list_manager.add_list(
        label=label,
        description="",
        list_type="mdblist",
        update_interval=update_interval,
        mdblist_config={
            "mdblist_url": url,
            "total_items": total_items,
            "mdblist_filters": mdblist_filters,
        },
    )


def _show_add_local_otaku_recent():
    """
    Create a Local + Otaku Recently Watched list. Only asks for a name.
    Returns the new list entry dict on success, or None if cancelled.
    """
    d = xbmcgui.Dialog()
    label = d.input("List name", defaultt="Recently Watched", type=xbmcgui.INPUT_ALPHANUM)
    if not label:
        return None
    return list_manager.add_list(label=label, description="", list_type="local_otaku_recent")


def _show_rename_local_otaku_recent(entry):
    """Rename a Local + Otaku Recently Watched list."""
    val = xbmcgui.Dialog().input(
        "List name", defaultt=entry["label"], type=xbmcgui.INPUT_ALPHANUM
    )
    if val and val != entry["label"]:
        list_manager.update_list(entry["id"], {"label": val})
        xbmcgui.Dialog().notification(
            _ADDON_NAME, "'{}' renamed.".format(val),
            xbmcgui.NOTIFICATION_INFO, 2000,
        )


def _show_add_local_fen_recent(kind):
    """
    Create a Local + Fen Recently Watched list (movies or series). Only asks for a name.
    kind: "movies" or "series"
    Returns the new list entry dict on success, or None if cancelled.
    """
    d = xbmcgui.Dialog()
    if kind == "movies":
        default_name = "Recently Watched Movies"
        list_type = "local_fen_recent_movies"
    else:
        default_name = "Recently Watched Series"
        list_type = "local_fen_recent_series"
    label = d.input("List name", defaultt=default_name, type=xbmcgui.INPUT_ALPHANUM)
    if not label:
        return None
    return list_manager.add_list(label=label, description="", list_type=list_type)


def _show_rename_local_fen_recent(entry):
    """Rename a Local + Fen Recently Watched list."""
    val = xbmcgui.Dialog().input(
        "List name", defaultt=entry["label"], type=xbmcgui.INPUT_ALPHANUM
    )
    if val and val != entry["label"]:
        list_manager.update_list(entry["id"], {"label": val})
        xbmcgui.Dialog().notification(
            _ADDON_NAME, "'{}' renamed.".format(val),
            xbmcgui.NOTIFICATION_INFO, 2000,
        )


def show_edit_mdblist(entry):
    """
    Menu-based edit dialog for MDBList entries.
    Returns True if changes were saved.

    Menu indices:
      0  Name
      1  MDBList URL
      2  Max items
      3  Sort by (API)
      4  Order (API)
      5  Media type (API)
      6  Genres include (API)
      7  Genres exclude (API)
      8  Released from (API)
      9  Released to (API)
      10 Append (API)
      11 Update interval
      12 Save
      13 Cancel
    """
    raw_filters = entry.get("mdblist_filters") or {}

    # Normalise append_to_response — stored as comma-string
    raw_append = raw_filters.get("append_to_response", "ratings")
    if isinstance(raw_append, list):
        raw_append = ",".join(raw_append)

    # Normalise genres — may be stored as list or missing (old entries had "genre" string)
    raw_inc = raw_filters.get("genres_include")
    raw_exc = raw_filters.get("genres_exclude")
    if raw_inc is None:
        old = raw_filters.get("genre", "")
        raw_inc = [old] if old else []
    if raw_exc is None:
        raw_exc = []

    # Backward-compat: infer mode for entries saved before dynamic dates existed
    raw_rf = raw_filters.get("released_from", "")
    raw_rt = raw_filters.get("released_to", "")
    raw_rf_mode = raw_filters.get("released_from_mode", "static" if raw_rf else "")
    raw_rt_mode = raw_filters.get("released_to_mode", "static" if raw_rt else "")

    working = {
        "label": entry["label"],
        "mdblist_url": entry.get("mdblist_url", ""),
        "total_items": entry.get("total_items", 50),
        "update_interval": entry.get("update_interval", 1),
        "filters": {
            "sort": raw_filters.get("sort", ""),
            "order": raw_filters.get("order", ""),
            "mediatype": raw_filters.get("mediatype", ""),
            "genres_include": list(raw_inc),
            "genres_exclude": list(raw_exc),
            "released_from": raw_rf,
            "released_from_mode": raw_rf_mode,
            "released_from_n": raw_filters.get("released_from_n", 12),
            "released_to": raw_rt,
            "released_to_mode": raw_rt_mode,
            "released_to_n": raw_filters.get("released_to_n", 12),
            "append_to_response": raw_append,
        },
    }

    changed = False
    _SORT_KEYS   = [""] + [o[1] for o in MDBLIST_SORT_OPTIONS]
    _SORT_LABELS = ["(default / no sort)"] + [o[0] for o in MDBLIST_SORT_OPTIONS]
    _APPEND_KEYS = [o[1] for o in MDBLIST_APPEND_OPTIONS]

    while True:
        f = working["filters"]
        sort_label  = next((o[0] for o in MDBLIST_SORT_OPTIONS if o[1] == f["sort"]), "(default)")
        mt_label    = next((o[0] for o in MDBLIST_MEDIATYPE_OPTIONS if o[1] == f["mediatype"]), "All types")
        inc_label   = ", ".join(f["genres_include"]) if f["genres_include"] else "(any)"
        exc_label   = ", ".join(f["genres_exclude"]) if f["genres_exclude"] else "(none)"
        append_label = f["append_to_response"] or "(none)"

        rf_label = _date_filter_label(f["released_from_mode"], f["released_from"], f["released_from_n"])
        rt_label = _date_filter_label(f["released_to_mode"], f["released_to"], f["released_to_n"])

        menu_items = [
            "Name:                  {}".format(working["label"]),
            "MDBList URL:           {}".format(working["mdblist_url"] or "(not set)"),
            "Max items:             {}".format(working["total_items"]),
            "Sort by (API):         {}".format(sort_label),
            "Order (API):           {}".format(f["order"] or "(default)"),
            "Media type (API):      {}".format(mt_label),
            "Genres include (API):  {}".format(inc_label),
            "Genres exclude (API):  {}".format(exc_label),
            "Released from (API):   {}".format(rf_label),
            "Released to (API):     {}".format(rt_label),
            "Append (API):          {}".format(append_label),
            "Update interval:       {} days".format(working["update_interval"]),
            "[COLOR green]Save[/COLOR]",
            "[COLOR red]Cancel[/COLOR]",
        ]

        SAVE_IDX   = len(menu_items) - 2
        CANCEL_IDX = len(menu_items) - 1

        choice = xbmcgui.Dialog().select("Edit: {}".format(working["label"]), menu_items)

        if choice < 0 or choice == CANCEL_IDX:
            break

        if choice == SAVE_IDX:
            # Client-side priority before saving
            fi = working["filters"]
            fi["genres_include"] = [g for g in fi["genres_include"] if g not in fi["genres_exclude"]]
            list_manager.update_list(entry["id"], {
                "label": working["label"],
                "mdblist_url": working["mdblist_url"],
                "total_items": working["total_items"],
                "mdblist_filters": working["filters"],
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
            cur_idx = _SORT_KEYS.index(f["sort"]) if f["sort"] in _SORT_KEYS else 0
            c = d.select("Sort by (API only)", _SORT_LABELS, preselect=cur_idx)
            if c >= 0:
                working["filters"]["sort"] = _SORT_KEYS[c]

        elif choice == 4:
            order_opts = [("(default)", ""), ("Ascending", "asc"), ("Descending", "desc")]
            cur_idx = next((i for i, o in enumerate(order_opts) if o[1] == f["order"]), 0)
            c = d.select("Sort order (API only)", [o[0] for o in order_opts], preselect=cur_idx)
            if c >= 0:
                working["filters"]["order"] = order_opts[c][1]

        elif choice == 5:
            mt_keys = [o[1] for o in MDBLIST_MEDIATYPE_OPTIONS]
            cur_idx = mt_keys.index(f["mediatype"]) if f["mediatype"] in mt_keys else 0
            c = d.select("Media type filter (API only)",
                         [o[0] for o in MDBLIST_MEDIATYPE_OPTIONS], preselect=cur_idx)
            if c >= 0:
                working["filters"]["mediatype"] = mt_keys[c]

        elif choice == 6:
            preselect = [i for i, g in enumerate(MDBLIST_GENRES) if g in f["genres_include"]]
            result = d.multiselect(
                "Genres to include (none selected = any)",
                MDBLIST_GENRES, preselect=preselect,
            )
            if result is not None:
                working["filters"]["genres_include"] = [MDBLIST_GENRES[i] for i in result]

        elif choice == 7:
            preselect = [i for i, g in enumerate(MDBLIST_GENRES) if g in f["genres_exclude"]]
            result = d.multiselect(
                "Genres to exclude (exclude wins on conflict)",
                MDBLIST_GENRES, preselect=preselect,
            )
            if result is not None:
                working["filters"]["genres_exclude"] = [MDBLIST_GENRES[i] for i in result]

        elif choice == 8:
            mode, static, n = _ask_date_filter(
                d, "Released from (API only)",
                f["released_from_mode"], f["released_from"], f["released_from_n"],
            )
            working["filters"]["released_from_mode"] = mode
            working["filters"]["released_from"] = static
            working["filters"]["released_from_n"] = n

        elif choice == 9:
            mode, static, n = _ask_date_filter(
                d, "Released to (API only)",
                f["released_to_mode"], f["released_to"], f["released_to_n"],
            )
            working["filters"]["released_to_mode"] = mode
            working["filters"]["released_to"] = static
            working["filters"]["released_to_n"] = n

        elif choice == 10:
            cur_append = f["append_to_response"]
            cur_list = [v.strip() for v in cur_append.split(",") if v.strip()]
            preselect = [i for i, k in enumerate(_APPEND_KEYS) if k in cur_list]
            result = d.multiselect(
                "Append to response (API only)",
                [o[0] for o in MDBLIST_APPEND_OPTIONS],
                preselect=preselect,
            )
            if result is not None:
                working["filters"]["append_to_response"] = ",".join(
                    _APPEND_KEYS[i] for i in result
                )

        elif choice == 11:
            keys = [o[1] for o in INTERVAL_OPTIONS]
            cur_idx = keys.index(working["update_interval"]) if working["update_interval"] in keys else 3
            interval_labels = ["OK (keep current)"] + [o[0] for o in INTERVAL_OPTIONS]
            c = d.select("Update interval", interval_labels, preselect=cur_idx + 1)
            if c > 0:
                working["update_interval"] = keys[c - 1]

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
            interval_labels = ["OK (keep current)"] + [o[0] for o in INTERVAL_OPTIONS]
            c = d.select("Update interval", interval_labels, preselect=cur_idx + 1)
            if c > 0:
                working["update_interval"] = keys[c - 1]

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
