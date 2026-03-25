import os

from logger import logger


def rebuild(anime_root, kodi_dir_name="_kodi"):
    """
    Walk anime_root one level deep (show dirs), then one more level (season dirs).
    Create directory symlinks in anime_root/<kodi_dir_name>/ pointing to each season dir.
    Remove stale symlinks that no longer have a corresponding source.

    Expected input layout:
        anime_root/
            Show Name/
                Season Name/   <- episode files live here
                Season 2/
            Another Show/
                Another Show/

    Resulting symlink layout (anime_root/<kodi_dir_name>/):
        Season Name        -> ../Show Name/Season Name/
        Season 2           -> ../Show Name/Season 2/
        Another Show       -> ../Another Show/Another Show/

    Returns (created, removed, errors) counts.
    Raises PermissionError with a helpful message on Windows if Developer Mode is off.
    """
    kodi_flat = os.path.join(anime_root, kodi_dir_name)
    logger.info("rebuild: anime_root=%r kodi_flat=%r" % (anime_root, kodi_flat))
    os.makedirs(kodi_flat, exist_ok=True)

    # Collect desired symlinks: {link_name: absolute_target_path}
    desired = {}
    for entry in os.scandir(anime_root):
        if not entry.is_dir(follow_symlinks=False) or entry.name == kodi_dir_name:
            continue
        logger.debug("rebuild: scanning show dir %r" % entry.name)
        for season in os.scandir(entry.path):
            if season.is_dir(follow_symlinks=False):
                logger.debug("rebuild: found season %r -> %r" % (season.name, season.path))
                desired[season.name] = season.path

    logger.info("rebuild: %d season dirs found" % len(desired))

    # Remove stale symlinks
    removed = 0
    for entry in os.scandir(kodi_flat):
        if entry.is_symlink() and entry.name not in desired:
            logger.info("rebuild: removing stale symlink %r" % entry.name)
            os.unlink(entry.path)
            removed += 1

    # Create missing symlinks
    created = 0
    errors = 0
    for name, target in desired.items():
        link = os.path.join(kodi_flat, name)
        if os.path.exists(link) or os.path.islink(link):
            logger.debug("rebuild: symlink already exists %r" % name)
            continue
        try:
            os.symlink(target, link, target_is_directory=True)
            logger.info("rebuild: created symlink %r -> %r" % (name, target))
            created += 1
        except OSError as e:
            if hasattr(e, "winerror") and e.winerror == 1314:
                raise PermissionError(
                    "Cannot create symlinks. Enable Developer Mode in "
                    "Windows Settings > System > For developers, then retry."
                ) from e
            logger.error("rebuild: failed to create symlink %r -> %r: %s" % (name, target, e))
            errors += 1

    logger.info("rebuild: done — created=%d removed=%d errors=%d" % (created, removed, errors))
    return created, removed, errors
