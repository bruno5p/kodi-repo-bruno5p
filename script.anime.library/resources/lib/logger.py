import xbmc
import xbmcaddon

_ADDON = xbmcaddon.Addon()
ADDON_ID = _ADDON.getAddonInfo("id")

try:
    text_type = unicode  # Python 2
except NameError:
    text_type = str  # Python 3


class logger:
    log_message_prefix = "[{} ({})]: ".format(ADDON_ID, _ADDON.getAddonInfo("version"))

    @staticmethod
    def log(message, level=xbmc.LOGDEBUG):
        prefix = logger.log_message_prefix
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        elif text_type is not str and isinstance(message, text_type):
            message = message.encode("utf-8")
            prefix = logger.log_message_prefix.encode("utf-8")
        xbmc.log(prefix + message, level)

    @staticmethod
    def info(message):
        logger.log(message, xbmc.LOGINFO)

    @staticmethod
    def warning(message):
        logger.log(message, xbmc.LOGWARNING)

    @staticmethod
    def error(message):
        logger.log(message, xbmc.LOGERROR)

    @staticmethod
    def debug(message):
        logger.log(message, xbmc.LOGDEBUG)
