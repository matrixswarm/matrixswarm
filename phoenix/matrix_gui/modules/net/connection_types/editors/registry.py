from .https_editor import HTTPSConnectionEditor
from .wss_editor import WSSConnectionEditor
from .email_editor import EmailConnectionEditor
from .discord_editor import DiscordConnectionEditor
from .telegram_editor import TelegramConnectionEditor
from .openai_editor import OpenAIConnectionEditor
from .slack_editor import SlackConnectionEditor
from .ssh_editor import SSHConnectionEditor
from .mysql_editor import MySQLConnectionEditor
from .cdn_editor import CDNConnectionEditor

CONNECTION_EDITOR_REGISTRY = {
    "https": HTTPSConnectionEditor,
    "wss": WSSConnectionEditor,
    "email": EmailConnectionEditor,
    "discord": DiscordConnectionEditor,
    "telegram": TelegramConnectionEditor,
    "openai": OpenAIConnectionEditor,
    "slack": SlackConnectionEditor,
    "ssh": SSHConnectionEditor,
    "mysql": MySQLConnectionEditor,
    "cdn": CDNConnectionEditor,
}
