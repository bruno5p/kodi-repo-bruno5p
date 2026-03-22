"""
Utility helpers: title selection, field mapping, image URL extraction.
"""

# Relation types from Jikan that we treat as Season 0 specials
SPECIAL_RELATION_TYPES = {"Movie", "OVA", "Special", "ONA", "Music"}

# Anime types considered "specials" when encountered via relations
SPECIAL_ANIME_TYPES = {"Movie", "OVA", "Special", "ONA", "Music"}

# Mapping from MAL content rating to MPAA-style labels
RATING_MAP = {
    "G - All Ages": "G",
    "PG - Children": "PG",
    "PG-13 - Teens 13 or older": "PG-13",
    "R - 17+ (violence & profanity)": "TV-14",
    "R+ - Mild Nudity": "TV-MA",
    "Rx - Hentai": "NC-17",
}

# Mapping from MAL airing status to Kodi status
STATUS_MAP = {
    "Finished Airing": "Ended",
    "Currently Airing": "Continuing",
    "Not yet aired": "Continuing",
}

TITLE_LANG_ENGLISH = 0
TITLE_LANG_ROMAJI = 1
TITLE_LANG_JAPANESE = 2


def pick_title(titles, language_pref=TITLE_LANG_ENGLISH):
    """
    Pick the best title from the titles list returned by Jikan.
    titles: list of {'type': 'English'|'Default'|'Japanese'|'Synonym'|..., 'title': str}
    language_pref: 0=English, 1=Romaji/Default, 2=Japanese
    Returns a string.
    """
    type_order = {
        TITLE_LANG_ENGLISH: ["English", "Default", "Synonym", "Japanese"],
        TITLE_LANG_ROMAJI: ["Default", "English", "Synonym", "Japanese"],
        TITLE_LANG_JAPANESE: ["Japanese", "Default", "English", "Synonym"],
    }.get(language_pref, ["English", "Default"])

    title_map = {}
    for entry in titles or []:
        t = entry.get("type", "")
        v = entry.get("title", "")
        if v:
            title_map[t] = v

    for t in type_order:
        if t in title_map:
            return title_map[t]

    # Last resort: first non-empty title
    for entry in titles or []:
        if entry.get("title"):
            return entry["title"]

    return "Unknown"


def pick_image_url(image_obj, prefer_large=True):
    """
    Pick the best image URL from a Jikan image object.
    image_obj: {'jpg': {'image_url': ..., 'large_image_url': ...}, 'webp': {...}}
    Returns URL string or empty string.
    """
    if not image_obj:
        return ""
    for fmt in ("webp", "jpg"):
        fmt_data = image_obj.get(fmt, {})
        if prefer_large and fmt_data.get("large_image_url"):
            return fmt_data["large_image_url"]
        if fmt_data.get("image_url"):
            return fmt_data["image_url"]
    return ""


def map_status(mal_status):
    """Map MAL airing status string to Kodi status string."""
    return STATUS_MAP.get(mal_status, "Continuing")


def map_mpaa(mal_rating):
    """Map MAL content rating string to MPAA-style label."""
    return RATING_MAP.get(mal_rating, "")


def extract_year(aired_obj):
    """
    Extract 4-digit year string from Jikan aired object.
    aired_obj: {'from': '2020-04-01T00:00:00+00:00', 'to': ..., 'prop': {...}}
    Returns year string like '2020', or empty string.
    """
    if not aired_obj:
        return ""
    from_date = aired_obj.get("from") or ""
    if from_date and len(from_date) >= 4:
        return from_date[:4]
    return ""


def extract_premiered(aired_obj):
    """
    Extract premiered date (YYYY-MM-DD) from Jikan aired object.
    Returns string like '2020-04-01', or empty string.
    """
    if not aired_obj:
        return ""
    from_date = aired_obj.get("from") or ""
    if from_date and len(from_date) >= 10:
        return from_date[:10]
    return ""


def collect_genres(anime_data):
    """
    Merge genres and themes into a single list of name strings.
    """
    genres = []
    for entry in anime_data.get("genres", []):
        name = entry.get("name", "")
        if name:
            genres.append(name)
    for entry in anime_data.get("themes", []):
        name = entry.get("name", "")
        if name and name not in genres:
            genres.append(name)
    return genres


def collect_studios(anime_data):
    """Return list of studio name strings."""
    return [s["name"] for s in anime_data.get("studios", []) if s.get("name")]


def encode_episode_url(mal_id, episode_num):
    """Encode a regular episode reference as a URL token."""
    return "{}|ep|{}".format(mal_id, episode_num)


def encode_special_url(original_mal_id, related_mal_id):
    """Encode a special/movie episode reference as a URL token."""
    return "{}|special|{}".format(original_mal_id, related_mal_id)


def decode_url(url):
    """
    Decode a URL token back into its parts.
    Returns dict with keys: 'mal_id', 'type' ('ep' or 'special'), 'value'
    """
    parts = url.split("|")
    if len(parts) == 3:
        return {"mal_id": parts[0], "type": parts[1], "value": parts[2]}
    return {"mal_id": url, "type": "show", "value": url}
