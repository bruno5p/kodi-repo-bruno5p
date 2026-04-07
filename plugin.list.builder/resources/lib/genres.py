"""
TMDb genre name -> numeric ID mappings.
TV source:    https://api.themoviedb.org/3/genre/tv/list
Movie source: https://api.themoviedb.org/3/genre/movie/list
"""

TV_GENRES = {
    "Action & Adventure": 10759,
    "Animation":          16,
    "Comedy":             35,
    "Crime":              80,
    "Documentary":        99,
    "Drama":              18,
    "Family":             10751,
    "Kids":               10762,
    "Mystery":            9648,
    "News":               10763,
    "Reality":            10764,
    "Romance":            10749,
    "Sci-Fi & Fantasy":   10765,
    "Soap":               10766,
    "Talk":               10767,
    "War & Politics":     10768,
    "Western":            37,
}

MOVIE_GENRES = {
    "Action":      28,
    "Adventure":   12,
    "Animation":   16,
    "Comedy":      35,
    "Crime":       80,
    "Documentary": 99,
    "Drama":       18,
    "Family":      10751,
    "Fantasy":     14,
    "History":     36,
    "Horror":      27,
    "Music":       10402,
    "Mystery":     9648,
    "Romance":     10749,
    "Sci-Fi":      878,
    "Thriller":    53,
    "War":         10752,
    "Western":     37,
}

SORT_OPTIONS = [
    ("Vote Count (desc)",   "vote_count.desc"),
    ("Vote Average (desc)", "vote_average.desc"),
    ("Popularity (desc)",   "popularity.desc"),
    ("Air Date (newest)",   "first_air_date.desc"),
    ("Air Date (oldest)",   "first_air_date.asc"),
]

LANGUAGE_OPTIONS = [
    ("(any)",        None),
    ("Japanese",     "ja"),
    ("Korean",       "ko"),
    ("Chinese",      "zh"),
    ("English",      "en"),
    ("Spanish",      "es"),
    ("French",       "fr"),
    ("German",       "de"),
    ("Italian",      "it"),
    ("Portuguese",   "pt"),
]

COUNTRY_OPTIONS = [
    ("(any)",          None),
    ("Japan",          "JP"),
    ("South Korea",    "KR"),
    ("China",          "CN"),
    ("Taiwan",         "TW"),
    ("Hong Kong",      "HK"),
    ("United States",  "US"),
    ("United Kingdom", "GB"),
    ("France",         "FR"),
    ("Germany",        "DE"),
]

INTERVAL_OPTIONS = [
    ("Daily",          1),
    ("Weekly",         7),
    ("Every 2 weeks",  14),
    ("Monthly",        30),
    ("Every 3 months", 90),
    ("Every 6 months", 180),
]

MEDIATYPE_OPTIONS = [
    ("TV Shows", "show"),
    ("Movies",   "movie"),
]


def get_genre_map(mediatype):
    """Return the genre name->ID dict for the given mediatype ('show' or 'movie')."""
    return TV_GENRES if mediatype == "show" else MOVIE_GENRES


def ids_to_names(genre_ids, mediatype):
    """Convert a list of genre IDs to their display names."""
    genre_map = get_genre_map(mediatype)
    reverse = {v: k for k, v in genre_map.items()}
    return [reverse.get(gid, str(gid)) for gid in (genre_ids or [])]
