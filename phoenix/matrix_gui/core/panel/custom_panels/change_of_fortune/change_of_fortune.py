"""Change of Fortune Phoenix panel."""
from matrix_gui.core.panel.custom_panels.world_watch.world_watch import WorldWatchPanel


class ChangeOfFortune(WorldWatchPanel):
    DISPLAY_NAME = 'Change of Fortune'
    ICON = '🔔'
    SERVICE_PREFIX = 'hive.change_of_fortune.'
    REPLY_EVENT = 'inbound.verified.change_of_fortune.config'
    HELP_TEXT = 'Watch a public announcement page for the product, release, or event in your keywords. The first check establishes a baseline; later relevant changes are analyzed by Oracle and linked to the source.'
