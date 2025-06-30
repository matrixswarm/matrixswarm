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

        "children": [
                {
                    "universal_id": "matrix-https",
                    "name": "matrix_https",
                    "filesystem": {
                        "folders": [],
                        "files": {}
                    },

                    "config": {
                        "service-manager": [{
                            "subscribe": ["agent_tree_updates"],
                            "scope": ["parent", "any"],     # who it serves
                            "auth": {"sig": True},
                            "priority": 10,                # lower = more preferred
                            "exclusive": False             # can other services respond?
                        }],
                    }
                },
                {
                    "universal_id": "email-check-1",
                    "name": "email_check",
                    "filesystem": {},
                    "config": {
                        "imap_host": os.getenv("EMAILCHECKAGENT_IMAP_HOST"),
                        "email": os.getenv("EMAILCHECKAGENT_EMAIL"),
                        "password": os.getenv("EMAILCHECKAGENT_PASSWORD"),
                        "report_to": os.getenv("EMAILCHECKAGENT_REPORT_TO", "mailman-1"),
                        "interval": int(os.getenv("EMAILCHECKAGENT_INTERVAL", 60))
                    },
                    "children": []
                },
                {
                    "universal_id": "agent-doctor-1",
                    "name": "agent_doctor",
                    "app": "matrix-core",
                    "children": []
                },
                {
                  "name": "tripwire_lite",
                  "universal_id": "tripwire-1",
                  "config": {
                    "watch_paths": ["core", "agent", "matrix_gui", "boot_directives"]
                  },
                  "delegated": [],
                  "filesystem": {},
                    "children": [
                              {
                                "universal_id": "logger-1",
                                "name": "logger",
                                "children": [
                                  {
                                    "universal_id": "logger-2",
                                    "name": "logger",
                                    "children": [
                                      {
                                        "universal_id": "logger-3",
                                        "name": "logger",
                                        "children": [
                                              {
                                                "universal_id": "logger-4",
                                                "name": "logger",
                                                "children": [

                                                    {
                                                        "universal_id": "worker-backup-3",
                                                        "name": "worker",
                                                        "children": []
                                                    }
                                                ]
                                              },



                                        ]
                                      }
                                    ]
                                  }
                                ]
                              }
                            ]
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
                        "role": ["hive.alert.send_alert_msg, hive.rpc.route"],
                        "scope": ["parent", "any"],     # who it serves
                        "auth": {"sig": True},
                        "priority": 10,                # lower = more preferred
                        "exclusive": False             # can other services respond?
                    }]
                }
        },


        ]
    }
