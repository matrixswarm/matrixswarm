from .https_provider import HTTPS
from .wss_provider import WSS
from .email_provider import Email
from .discord_provider import Discord
from .telegram_provider import Telegram
from .openai_provider import OpenAI
from .slack_provider import Slack
from .ssh_provider import SSH
from .mysql_provider import MySQL
from .cdn_provider import CDN

CONNECTION_PROVIDER_REGISTRY = {
    "https": HTTPS(),
    "wss": WSS(),
    "email": Email(),
    "discord": Discord(),
    "telegram": Telegram(),
    "openai": OpenAI(),
    "slack": Slack(),
    "ssh": SSH(),
    "mysql": MySQL(),
    "cdn": CDN(),
}
