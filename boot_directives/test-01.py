import os
from dotenv import load_dotenv
load_dotenv()

matrix_directive = {

        "universal_id": 'matrix',
        "name": "matrix",
        "filesystem": {
            "folders": [],
            "files": {}
        },

        "children": [{
                "universal_id": "matrix-https",
                "name": "matrix_https",
                "delegated": [],
                "filesystem": {
                    "folders": [],
                    "files": {}
                    }
                },
                {
                "universal_id": "websocket-relay",
                "name": "matrix_websocket",
                "config": {
                    "port": 8765,
                    "factories": {
                        "reflex.health.status_report": {}
                    },
                    "service-manager": [{
                        "role": ["hive.alert.send_alert_msg"],
                        "scope": ["parent", "any"],     # who it serves
                        "auth": {"sig": True},
                        "priority": 10,                # lower = more preferred
                        "exclusive": False             # can other services respond?
                    }]
                },
                "filesystem": {},
                "delegated": []
                },
                {
                    "universal_id": "mysql-red-phone",
                    "name": "mysql_watchdog",
                    "app": "mysql-demo",
                    "config": {
                        "mysql_port": 3306,
                        "socket_path": "/var/run/mysqld/mysqld.sock",
                        "service_name": "mariadb",
                        "check_interval_sec": 20,
                        "restart_limit": 3,
                        "alert_thresholds": {
                            "uptime_pct_min": 90,
                            "slow_restart_sec": 10
                        },
                        "role": "mysql-alarm",
                    }
                },
                {
                    "universal_id": "redis-hammer",
                    "name": "redis_watchdog",
                    "app": "redis-core",
                    "config": {
                        "check_interval_sec": 10,
                        "restart_limit": 3,
                        "redis_port": 6379,
                        "always_alert": 1,
                        "socket_path": "/var/run/redis/redis-server.sock",
                        "service_name": "redis"
                    }
                },
                {
                    "universal_id": "discord-delta-5",
                    "name": "discord",
                    "app": "mysql-demo",
                    "filesystem": {
                        "folders": []
                    },
                    "config": {
                        "bot_token": os.getenv("DISCORD_TOKEN"),
                        "channel_id": os.getenv("DISCORD_CHANNEL_ID"),
                        "service-manager": [{
                            "role": ["comm", "comm.security", "hive.alert.send_alert_msg", "comm.*"],
                            "scope": ["parent", "any"],     # who it serves
                            "auth": {"sig": True},
                            "priority": 10,                # lower = more preferred
                            "exclusive": False             # can other services respond?
                        }]
                    }
                },
                {
                    "universal_id": "telegram-bot-father-2",
                    "name": "telegram_relay",
                    "app": "mysql-demo",
                    "filesystem": {
                        "folders": []
                    },
                    "config": {
                        "bot_token": os.getenv("TELEGRAM_API_KEY"),
                        "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
                        "service-manager": [{
                            "role": ["comm", "comm.security", "comm.*, hive.alert.send_alert_msg"],
                            "scope": ["parent", "any"],     # who it serves
                            "auth": {"sig": True},
                            "priority": 10,                # lower = more preferred
                            "exclusive": False             # can other services respond?
                        }]
                    }
                },

                {
                    "universal_id": "commander-1",
                    "name": "commander",
                    "app": "matrix-core",
                    "children": []
                },
                {
                    "universal_id": "apache_watchdog-1",
                    "name": "apache_watchdog",
                    "app": "matrix-core",
                    "config": {
                        "check_interval_sec": 10,
                        "service_name": "httpd",  # change to "httpd" for RHEL/CentOS
                        "ports": [80, 443],
                        "restart_limit": 3,
                        "always_alert": 1,
                        "alert_cooldown": 300
                }
                },
                {
                    "universal_id": "nginx-sentinel",
                    "name": "nginx_watchdog",
                    "app": "swarm-edge",
                    "config": {
                        "check_interval_sec": 10,
                        "always_alert": 1,
                        "restart_limit": 3,
                        "service_name": "nginx",
                        "ports": [86],
                        "alert_cooldown": 300
                    }
                },



        ]
    }
