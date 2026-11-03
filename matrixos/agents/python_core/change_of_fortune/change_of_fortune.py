"""Watch official pages for product and service end-of-life announcements."""
import os
import sys

for path in (os.getenv('SITE_ROOT'), os.getenv('AGENT_PATH')):
    if path:
        sys.path.insert(0, path)

from world_watch.agent import WatchAgent
from world_watch.engine import FortuneEngine


class Agent(WatchAgent):
    STATE_NAMESPACE = 'change_of_fortune'
    REPLY_HANDLER = 'change_of_fortune.config'
    ENGINE_CLASS = FortuneEngine
    DISPLAY_NAME = 'Change of Fortune'
    LOG_LABEL = 'CHANGE-OF-FORTUNE'
    ICON = '⌛'


if __name__ == '__main__':
    Agent().boot()
