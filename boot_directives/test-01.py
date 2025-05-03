import os
from dotenv import load_dotenv
load_dotenv()

matrix_directive = {
        "universal_id": 'matrix',
        "name": "matrix",
        "filesystem": {
            "folders": [
                {
                    'name': 'payload',
                    'type': 'd',
                    'content': None
                },
            ],
            "files": {}
        },

        "children": [{
                "universal_id": "matrix-https",
                "name": "matrix_https",
                "delegated": [],
                "filesystem": {
                    "folders": [
                                {
                                'name': 'payload',
                                'type': 'd',
                                'content': None
                                },
                            ],
                    "files": {}
                    }
                },
                {
                    "universal_id": "scavenger-strike",
                    "name": "scavenger",
                    "filesystem": {
                        "folders": []
                    },
                    "config": {}
                },
                {
                    "universal_id": "telegram-relay-1",
                    "name": "telegram_relay",
                    "config": {
                        "bot_token": os.getenv("TELEGRAM_API_KEY"),
                        "chat_id": os.getenv("TELEGRAM_CHAT_ID")
                    },
                    "children": []

                },
                {
                    "universal_id": "mailman-1",
                    "name": "mailman",
                    "filesystem": {
                        "folders": [
                            {"name": "payload", "type": "d", "content": None},
                            {"name": "mail", "type": "d", "content": None},
                            {"name": "tally", "type": "d", "content": None},
                            {"name": "incoming", "type": "d", "content": None}
                        ]
                    }
                },

                {
                    "universal_id": "commander-1",
                    "name": "commander",
                    "children": [
                        {
                            "universal_id": "commander-2",
                            "name": "commander",
                            "children": []
                        },
                    ]
                },
                {
                    "universal_id": "oracle-1",
                    "name": "oracle",
                    "filesystem": {
                        "folders": [
                            {
                                "name": "payload",
                                "type": "d",
                                "content": None
                            }
                        ],
                        "files": {}
                    },
                    "children": []
                },

                {
                    "universal_id": "pinger-1",
                    "name": "uptime_pinger",
                    "filesystem": {
                        "folders": [
                            {"name": "payload", "type": "d", "content": None}
                        ]
                    },
                    "config": {
                        "targets": ["https://dragoart.com", "https://matrixswarm.com"],
                        "interval_sec": 15,
                        "alert_to": "mailman-1"
                    }
                },
                {
                    "universal_id": "metric-1",
                    "name": "metric",
                    "filesystem": {
                        "folders": [
                            {"name": "payload", "type": "d", "content": None}
                        ]
                    },
                    "config": {
                        "interval_sec": 10,
                        "report_to": "mailman-1",
                        "oracle": "oracle-1"
                    }
                },

                {
                    "universal_id": "scraper-1",
                    "name": "scraper",
                    "filesystem": {
                        "folders": [
                            {"name": "payload", "type": "d", "content": None}
                        ]
                    },
                    "config": {
                        "report_to": "mailman-1"
                    }
                },
                {
                    "universal_id": "discord-relay-1",
                    "name": "discord",
                    "filesystem": {
                        "folders": [
                            {"name": "payload", "type": "d"},
                        ]
                    },
                    "config": {
                        "bot_token": os.getenv("DISCORD_TOKEN"),
                        "channel_id": os.getenv("DISCORD_CHANNEL_ID"),
                    }
                },
        ]
    }
