"""
MDBList client — JSON export (no key) and REST API (with key).

JSON export:  https://mdblist.com/lists/user/listname/json/
REST API:     https://mdblist.com/api/lists/user/listname/items/?apikey=…
"""

import requests

from resources.lib.logger import logger

# Genre names as accepted by the MDBList API genre filter.
# Source: https://mdblist.com/shows/ and https://mdblist.com/movies/
MDBLIST_GENRES = [
    "Action",
    "Adventure",
    "Animation",
    "Comedy",
    "Crime",
    "Documentary",
    "Drama",
    "Family",
    "Fantasy",
    "History",
    "Horror",
    "Kids",
    "Music",
    "Mystery",
    "News",
    "Reality",
    "Romance",
    "Science Fiction",
    "Sport",
    "Talk",
    "Thriller",
    "War",
    "Western",
]

# API sort field values accepted by MDBList
MDBLIST_SORT_OPTIONS = [
    ("List rank", "rank"),
    ("MDB score", "score"),
    ("Title", "title"),
    ("IMDb rating", "imdbrating"),
    ("MDB rating", "mdbrating"),
    ("Release date", "released"),
    ("Date added", "added"),
]

# mediatype values for the API filter
MDBLIST_MEDIATYPE_OPTIONS = [
    ("All types", ""),
    ("Movies", "movie"),
    ("TV shows", "show"),
]

# append_to_response values — enrich API response with extra data
MDBLIST_APPEND_OPTIONS = [
    ("Ratings", "ratings"),
    ("Reviews", "reviews"),
    ("Keywords", "keywords"),
]


def _normalize_url(url):
    """Convert any MDBList list URL to its /json/ endpoint."""
    clean = url.rstrip("/")
    if not clean.endswith("/json"):
        clean += "/json"
    return clean + "/"


def _extract_slug(url):
    """
    Extract the user/listname slug from a MDBList URL.

    Handles:
      https://mdblist.com/lists/username/listname
      https://mdblist.com/lists/username/listname/
      https://mdblist.com/lists/username/listname/json/
    Returns e.g. "username/listname", or "" on failure.
    """
    clean = url.rstrip("/")
    if clean.endswith("/json"):
        clean = clean[:-5]
    clean = clean.rstrip("/")
    marker = "/lists/"
    idx = clean.find(marker)
    if idx == -1:
        return ""
    return clean[idx + len(marker) :]


def _map_item(item, rank):
    """
    Map a MDBList item (export or API) to the items_list_*.json format.

    Fields present in both export and API responses:
      tmdb_id, imdb_id, tvdb_id, title, year, mediatype/type, rank.
    poster_path is never provided by MDBList — Bingie fetches art from TMDb.
    """
    tmdb_id = item.get("tmdb_id") or item.get("id")
    if not tmdb_id:
        return None

    mediatype = item.get("mediatype") or item.get("type") or "movie"
    if mediatype in ("show", "tvshow", "tv"):
        mediatype = "show"
    else:
        mediatype = "movie"

    return {
        "id": tmdb_id,
        "rank": item.get("rank", rank),
        "adult": 0,
        "title": item.get("title") or item.get("name") or "",
        "imdb_id": item.get("imdb_id"),
        "tvdb_id": item.get("tvdb_id"),
        "language": None,
        "mediatype": mediatype,
        "release_year": item.get("year") or item.get("release_year"),
        "spoken_language": None,
        "poster_path": None,
    }


def get_mdblist_items(url, total_items=None):
    """
    DEPRECATED — use get_mdblist_items_api() instead.

    Fetch items from a MDBList URL (public JSON export, no API key needed).

    Accepts both:
    - https://mdblist.com/lists/username/listname
    - https://mdblist.com/lists/username/listname/json/

    Returns a list of item dicts in items_list_*.json format.
    Items without a tmdb_id are silently skipped.
    """
    logger.warning(
        "mdblist_api: get_mdblist_items() is deprecated — use get_mdblist_items_api()"
    )
    json_url = _normalize_url(url)
    logger.info("mdblist_api: fetching {}".format(json_url))

    try:
        response = requests.get(json_url, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.error("mdblist_api: request failed: {}".format(e))
        return []

    if isinstance(data, list):
        items_raw = data
    else:
        items_raw = data.get("json") or data.get("items") or []

    items = []
    for i, raw in enumerate(items_raw):
        if total_items and len(items) >= total_items:
            break
        mapped = _map_item(raw, i + 1)
        if mapped:
            items.append(mapped)
        else:
            logger.debug(
                "mdblist_api: skipped item with no tmdb_id at index {}".format(i)
            )

    logger.info("mdblist_api: fetched {} items from {}".format(len(items), json_url))
    return items


def get_mdblist_items_api(url, api_key, total_items=50, filters=None):
    """
    Fetch list items via the MDBList REST API.

    Endpoint: GET https://api.mdblist.com/lists/{username}/{listname}/items

    Args:
        url:         MDBList list URL (any form — slug is extracted automatically)
        api_key:     MDBList API key string
        total_items: maximum number of items to return (maps to the 'limit' param)
        filters:     optional dict with keys:
                       sort               - sort field (see MDBLIST_SORT_OPTIONS)
                       order              - "asc" or "desc"
                       mediatype          - "" | "movie" | "show"
                                           (handled client-side from response arrays)
                       genres_include     - list of genre name strings ([] = any)
                                           sent as API 'filter_genre' + 'genre_operator=or'
                       genres_exclude     - list of genre name strings ([] = none)
                                           filtered client-side; requires 'genres' in
                                           append_to_response (added automatically)
                       released_from      - "YYYY-MM-DD" or ""
                       released_to        - "YYYY-MM-DD" or ""
                       append_to_response - comma-separated string or list of values
                                           e.g. "ratings" or ["ratings", "reviews"]

    Genre logic:
        Exclude takes priority — genres in both lists are excluded.
        Included genres are sent to the API via filter_genre (OR logic).
        Excluded genres are filtered client-side from the response; 'genres' is
        automatically appended to append_to_response when genres_exclude is set.

    Response note:
        The API returns separate 'movies' and 'shows' arrays; mediatype filter
        selects one or both before further processing.

    Returns a list of item dicts in items_list_*.json format.
    Items without a tmdb_id are silently skipped.
    """
    slug = _extract_slug(url)
    if not slug:
        logger.error(
            "mdblist_api: could not extract slug from '{}' — check the URL format".format(url)
        )
        return []

    api_url = "https://api.mdblist.com/lists/{}/items".format(slug)
    filters = filters or {}

    params = {"apikey": api_key, "limit": total_items}

    sort = filters.get("sort", "")
    if sort:
        params["sort"] = sort

    order = filters.get("order", "")
    if order:
        params["order"] = order

    # --- genre include (API-side) / exclude (client-side) ---
    genres_include = list(filters.get("genres_include") or [])
    genres_exclude = list(filters.get("genres_exclude") or [])

    # Backward compat: old single "genre" string field
    if not genres_include and not genres_exclude:
        old_genre = filters.get("genre", "")
        if old_genre:
            genres_include = [old_genre]

    # Exclude takes priority: strip from include before sending to API
    if genres_exclude:
        genres_include = [g for g in genres_include if g not in genres_exclude]

    if genres_include:
        params["filter_genre"] = ",".join(genres_include)
        params["genre_operator"] = "or"

    released_from = filters.get("released_from", "")
    if released_from:
        params["released_from"] = released_from

    released_to = filters.get("released_to", "")
    if released_to:
        params["released_to"] = released_to

    append = filters.get("append_to_response", "")
    if isinstance(append, list):
        append = ",".join(append)
    # Auto-add "genres" when client-side exclude is needed
    if genres_exclude:
        parts = [p.strip() for p in append.split(",") if p.strip()]
        if "genres" not in parts:
            parts.append("genres")
        append = ",".join(parts)
    if append:
        params["append_to_response"] = append

    logger.info(
        "mdblist_api: API fetch {} params={}".format(
            api_url, {k: v for k, v in params.items() if k != "apikey"}
        )
    )

    try:
        response = requests.get(api_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.error("mdblist_api: API request failed: {}".format(e))
        return []

    if isinstance(data, dict) and "error" in data:
        logger.error("mdblist_api: API error: {}".format(data.get("error")))
        return []

    # Response has separate movies/shows arrays; mediatype filter selects which to use
    mediatype_filter = filters.get("mediatype", "")
    if isinstance(data, dict):
        if mediatype_filter == "movie":
            items_raw = data.get("movies") or []
        elif mediatype_filter == "show":
            items_raw = data.get("shows") or []
        else:
            items_raw = (data.get("movies") or []) + (data.get("shows") or [])
    elif isinstance(data, list):
        items_raw = data
    else:
        items_raw = []

    exclude_set = set(genres_exclude)
    items = []
    for i, raw in enumerate(items_raw):
        # Client-side genre exclude (requires genres in append_to_response)
        if exclude_set:
            raw_genres = raw.get("genres") or []
            item_genres = set()
            for g in raw_genres:
                item_genres.add(g.get("name", g) if isinstance(g, dict) else str(g))
            if item_genres & exclude_set:
                logger.debug("mdblist_api: excluded item '{}' — genre match".format(
                    raw.get("title", i)
                ))
                continue

        mapped = _map_item(raw, i + 1)
        if mapped:
            items.append(mapped)
        else:
            logger.debug(
                "mdblist_api: API skipped item with no tmdb_id at index {}".format(i)
            )

    logger.info("mdblist_api: API fetched {} items from {}".format(len(items), api_url))
    return items
