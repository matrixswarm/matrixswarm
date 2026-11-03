"""Watch and retain public offer and policy changes."""
import os
import sys

for path in (os.getenv('SITE_ROOT'), os.getenv('AGENT_PATH')):
    if path:
        sys.path.insert(0, path)

from world_watch.agent import WatchAgent
from world_watch.engine import PromiseEngine


class Agent(WatchAgent):
    STATE_NAMESPACE = 'promise_keeper'
    REPLY_HANDLER = 'promise_keeper.config'
    ENGINE_CLASS = PromiseEngine
    DISPLAY_NAME = 'Promise Keeper'
    LOG_LABEL = 'PROMISE-KEEPER'
    ICON = '📜'


if __name__ == '__main__':
    Agent().boot()
