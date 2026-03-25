import json
import os

import xbmc

from logger import logger


def get_anime_sources(kodi_dir_name="_kodi"):
    """
    Query Kodi for all configured video sources and return those whose path
    contains the word 'anime' (case-insensitive).

    For each matching source, derives the anime_root:
      - If the source path already ends with kodi_dir_name (e.g. .../Anime/_kodi/)
        the anime_root is its parent directory.
      - Otherwise the source path itself is the anime_root.

    Returns a list of (anime_root, kodi_flat) tuples.
    """
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "Files.GetSources",
        "params": {"media": "video"},
        "id": 1,
    })
    raw = xbmc.executeJSONRPC(payload)
    logger.debug("get_anime_sources: Files.GetSources response=%s" % raw)

    sources = json.loads(raw).get("result", {}).get("sources", [])
    logger.info("get_anime_sources: %d total video sources found" % len(sources))

    anime_sources = []
    for source in sources:
        path = source.get("file", "")
        label = source.get("label", "")
        logger.debug("get_anime_sources: checking source label=%r path=%r" % (label, path))

        if "anime" not in path.lower():
            logger.debug("get_anime_sources: skipped (no 'anime' in path)")
            continue

        # Strip trailing slashes for reliable basename comparison
        path_clean = path.rstrip("/\\")
        basename = os.path.basename(path_clean)

        if basename.lower() == kodi_dir_name.lower():
            # Source points at the _kodi/ flat dir — parent is the anime root
            anime_root = os.path.dirname(path_clean)
        else:
            anime_root = path_clean

        kodi_flat = os.path.join(anime_root, kodi_dir_name)
        logger.info("get_anime_sources: matched — label=%r anime_root=%r kodi_flat=%r"
                    % (label, anime_root, kodi_flat))
        anime_sources.append((anime_root, kodi_flat))

    logger.info("get_anime_sources: %d anime source(s) identified" % len(anime_sources))
    return anime_sources


def scan_library():
    """
    Trigger a full Kodi VideoLibrary scan across all configured sources.

    No 'directory' parameter is passed: passing a specific path causes Kodi
    to treat it as a new unregistered source and scrape the folder name itself
    rather than its contents.
    """
    logger.info("scan_library: triggering full VideoLibrary.Scan")
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "VideoLibrary.Scan",
        "params": {"showdialogs": True},
        "id": 1,
    })
    result = xbmc.executeJSONRPC(payload)
    logger.info("scan_library: response=%s" % result)
