import sys
from resources.lib.logger import logger
from resources.lib import router

if __name__ == "__main__":
    args = sys.argv[1:]

    if len(args) >= 2:
        # New convention: RunScript(script.media.router, anime, 12345)
        media_type = args[0].lower()
        media_id = args[1]
    elif len(args) == 1:
        # Legacy: RunScript(script.media.router, 12345)  — assumes anime/MAL
        media_type = "anime"
        media_id = args[0]
    else:
        media_type = "anime"
        media_id = ""

    logger.info("Media Router started: type={} id={}".format(media_type, media_id))
    router.run(media_type, media_id)
