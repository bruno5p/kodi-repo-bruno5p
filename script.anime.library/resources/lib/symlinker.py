import os

from logger import logger

VIDEO_EXTS = {'.mkv', '.mp4', '.avi', '.m4v', '.mov', '.wmv', '.flv', '.ts', '.m2ts'}


def _has_video_files(path):
    """Return True if the directory directly contains at least one video file."""
    for entry in os.scandir(path):
        if entry.is_file() and os.path.splitext(entry.name)[1].lower() in VIDEO_EXTS:
            return True
    return False


def _collect_episode_dirs(path, kodi_dir_name, desired):
    """
    Recursively walk path to find every directory that directly contains video
    files (an "episode dir").  When found, register it in desired under its
    own name.  Directories that contain no video files are traversed further.

    Supports any nesting depth, so these patterns all work:

        anime_root/Title/<ep files>                      (flat show)
        anime_root/Title/Season Title/<ep files>         (show + seasons)
        anime_root/Letter/Title/Season Title/<ep files>  (letter-grouped)
    """
    for entry in os.scandir(path):
        if not entry.is_dir(follow_symlinks=False) or entry.name == kodi_dir_name:
            continue
        if _has_video_files(entry.path):
            name = entry.name
            if name in desired:
                logger.warning(
                    "rebuild: name collision for %r — keeping %r, ignoring %r"
                    % (name, desired[name], entry.path)
                )
            else:
                logger.debug("rebuild: episode dir %r -> %r" % (name, entry.path))
                desired[name] = entry.path
        else:
            _collect_episode_dirs(entry.path, kodi_dir_name, desired)


def rebuild(anime_root, kodi_dir_name="_kodi"):
    """
    Recursively find every directory under anime_root that directly contains
    video files (an "episode dir") and create a symlink to it inside
    anime_root/<kodi_dir_name>/.  Stale symlinks are removed.

    Supported layouts (any nesting depth):
        anime_root/
            Title/<ep files>                       <- flat show, no seasons
            Title/Season Title/<ep files>          <- show with seasons
            Letter/Title/Season Title/<ep files>   <- letter-grouped with seasons
            Letter/Title/<ep files>                <- letter-grouped, flat

    Resulting symlink layout (anime_root/<kodi_dir_name>/):
        Title              -> ../Title/
        Season Title       -> ../Title/Season Title/
        Season Title       -> ../Letter/Title/Season Title/

    Returns (created, removed, errors) counts.
    Raises PermissionError with a helpful message on Windows if Developer Mode is off.
    """
    kodi_flat = os.path.join(anime_root, kodi_dir_name)
    logger.info("rebuild: anime_root=%r kodi_flat=%r" % (anime_root, kodi_flat))
    os.makedirs(kodi_flat, exist_ok=True)

    # Collect desired symlinks: {link_name: absolute_target_path}
    desired = {}
    _collect_episode_dirs(anime_root, kodi_dir_name, desired)

    logger.info("rebuild: %d episode dirs found" % len(desired))

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
