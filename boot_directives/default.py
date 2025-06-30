import os
from dotenv import load_dotenv
load_dotenv()

#MATRIX CORE DEPLOYMENT
matrix_directive = {
    "universal_id": 'matrix',
    "name": "matrix",
    "filesystem": {
        "folders": [],
        "files": {}
    },

    "children": [

        #MATRIX PROTECTION LAYER 4 SENTINELS
        #4th SENTINEL WATCHES MATRIX, REST WATCH SENTINEL IN FRONT
        #ONLY WAY TO KILL MATRIX WOULD BE TO KILL THEM ALL, TAKING ANY COMBO OF 4 OUT DOES NOTHING
        {
            "universal_id": "guardian-1",
            "name": "sentinel",
            "app": "matrix-core",
            "filesystem": {},
            "config": {"matrix_secure_verified": 1},
            "children": [
                {
                    "universal_id": "guardian-2",
                    "name": "sentinel",
                    "app": "matrix-core",
                    "filesystem": {},
                    "config": {"matrix_secure_verified": 1},
                    "children": [
                        {
                            "universal_id": "guardian-3",
                            "name": "sentinel",
                            "app": "matrix-core",
                            "filesystem": {},
                            "config": {"matrix_secure_verified": 1},
                            "children": [
                                {
                                    "universal_id": "guardian-4",
                                    "name": "sentinel",
                                    "app": "matrix-core",
                                    "filesystem": {},
                                    "config": {
                                        "matrix_secure_verified": 1,
                                        "watching": "the Queen",
                                        "universal_id_under_watch": "matrix"
                                    }
                                }
                            ]
                        }
                    ]
                }
            ]
        },

        {
        "universal_id": "matrix-https",
        "name": "matrix_https",
        "delegated": [],
        "app": "matrix-core",
        "filesystem": {
            "folders": [],
                "files": {}
            }
        },
        {
            "universal_id": "scavenger-strike",
            "name": "scavenger",
            "app": "matrix-core",
            "filesystem": {
                "folders": [],
            },
            "config": { }
        },

        {
            "universal_id": "commander-1",
            "name": "commander",
            "app": "matrix-core",
            "children": []
        },

        {
            "universal_id": "service-registry-1",
            "name": "service_registry",
            "filesystem": {},
            "config": {
              "confirm": "YES",

            }
        },
        {
            "universal_id": "alarm-streamer-1",
            "name": "alarm_streamer",
            "children": [

                        {
                          "universal_id": "discord-relay-1",
                          "name": "discord_relay",
                          "filesystem": {
                            "folders": []
                          },
                          "config": {
                            "bot_token": os.getenv("DISCORD_TOKEN"),
                            "channel_id": os.getenv("DISCORD_CHANNEL_ID"),
                            "role": "alarm_listener",
                            "factories": {
                              "alert.subscriber": {
                                  "levels": ["critical", "warning"],
                                  "webhook_url": os.getenv("DISCORD_WEBHOOK_ALERT_URL"),
                                  "bot_token": os.getenv("DISCORD_TOKEN"),
                                  "channel_id": os.getenv("DISCORD_CHANNEL_ID"),
                              }
                            }
                          }
                        },
                        {
                          "universal_id": "telegram-relay-1",
                          "name": "telegram_relay",
                          "filesystem": {
                            "folders": []
                          },
                          "config": {
                            "bot_token": os.getenv("TELEGRAM_API_KEY"),
                            "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
                            "role": "alarm_listener",
                            "factories": {
                              "alert.subscriber": {
                                  "levels": ["critical", "warning"],
                                  "bot_token": os.getenv("TELEGRAM_API_KEY"),
                                  "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
                              }
                            }
                          }
                        }
                    ]
        },
        {
        "universal_id": "oracle-1",
        "name": "oracle",
        "filesystem": {
            "folders": [],
            "files": {}
        },
        "children": []
        },
        {
          "universal_id": "websocket-relay",
          "name": "matrix_websocket",
          "config": {
            "port": 8765,
            "factories": {
                "reflex.health.status_report": {}
            },
          },
          "filesystem": {},
          "delegated": []
        }
    ]
}