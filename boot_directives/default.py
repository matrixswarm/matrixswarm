import os
from dotenv import load_dotenv
load_dotenv()

#MATRIX CORE DEPLOYMENT
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

    "children": [

        #MATRIX PROTECTION LAYER 4 SENTINELS
        {
            "universal_id": "guardian-1",
            "name": "sentinel",
            "app": "matrix-core",
            "filesystem": {},
            "config": {},
            "children": [
                {
                    "universal_id": "guardian-2",
                    "name": "sentinel",
                    "app": "matrix-core",
                    "filesystem": {},
                    "children": [
                        {
                            "universal_id": "guardian-3",
                            "name": "sentinel",
                            "app": "matrix-core",
                            "filesystem": {},
                            "config": {},
                            "children": [
                                {
                                    "universal_id": "guardian-4",
                                    "name": "sentinel",
                                    "app": "matrix-core",
                                    "filesystem": {},
                                    "config": {
                                        "watching": "the Queen",
                                        "universal_id": "matrix"
                                    }
                                }
                            ]
                        }
                    ],
                    "config": {}
                }
            ]
        },
        {
            "universal_id": "context-agent-1",
            "name": "app_context",
            "app": "matrix-core",
            "children": []
        },
        {
            "universal_id": "resolver-1",
            "name": "resolver",
            "app": "matrix-core",
            "children": []
        },
        {
        "universal_id": "matrix-https",
        "name": "matrix_https",
        "delegated": [],
        "app": "matrix-core",
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
            "app": "matrix-core",
            "filesystem": {
                "folders": []
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
            "universal_id": "telegram-relay-1",
            "name": "telegram_relay",
            "config": {
                "bot_token": os.getenv("TELEGRAM_API_KEY"),
                "chat_id": os.getenv("TELEGRAM_CHAT_ID")
            },
            "children": []

        },
        {
            "universal_id": "logger-2",
            "name": "logger",
            "children": []
        },
    ]
}