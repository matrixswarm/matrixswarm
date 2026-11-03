"""Promise Keeper Phoenix panel."""
from matrix_gui.core.panel.custom_panels.world_watch.world_watch import WorldWatchPanel


class PromiseKeeper(WorldWatchPanel):
    DISPLAY_NAME = 'Promise Keeper'
    ICON = '📜'
    SERVICE_PREFIX = 'hive.promise_keeper.'
    REPLY_EVENT = 'inbound.verified.promise_keeper.config'
    HELP_TEXT = 'Watch a public offer or terms page. The first check saves a private baseline; later material changes are sent to Oracle for an attributed alert. Verify the source and your own contract.'
