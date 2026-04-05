import sys
from resources.lib.logger import logger
from resources.lib import ui, auth

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    mal_id = sys.argv[2] if len(sys.argv) > 2 else ""

    logger.info("MAL Manager started action={} mal_id={}".format(action, mal_id))

    if action == "auth":
        auth.run_auth_flow()
    else:
        # Default: open the manager dialog for a given MAL ID
        if not mal_id and action.isdigit():
            # Support calling with just: RunScript(script.mal.manager, <mal_id>)
            mal_id = action
        ui.show_manager(mal_id)
