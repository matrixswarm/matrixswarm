from dotenv import load_dotenv
import os
import sys
import time
load_dotenv()
from agent.core.path_manager import PathManager
from agent.core.core_spawner import CoreSpawner
from agent.core.tree_parser import TreeParser
from agent.core.class_lib.processes.reaper import Reaper
cp = CoreSpawner()

import json

MATRIX_UUID = "matrix"
BOOTLOADER_UUID = "bootloader"
UNIVERSE_ID = "bb" #big bang
pm = PathManager()

paths={
    "pod": "pod",
    "agent": "agent",
    "comm": "comm",
}

pm.add_paths(paths)

#print(pm.construct_path("agent",str(uuid.uuid4()),'notify'))
#exit()

def boot():
    #encryption_key = load_or_create_key()
    #core = ProtectedCore(encryption_key)

    hard_reset = True

    matrix_directive = {
        "permanent_id": 'matrix',
        "children": [

                {
                "permanent_id": "matrix-https",
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
                    "permanent_id": "commander-2",
                    "name": "commander",
                    "children": []
                },
                {
                    "permanent_id": "email-check-1",
                    "name": "email_check",
                    "filesystem": {
                        "folders": [
                            {"name": "payload", "type": "d", "content": None}
                        ]
                    },
                    "config": {
                        "imap_host": os.getenv("EMAILCHECKAGENT_IMAP_HOST"),
                        "email": os.getenv("EMAILCHECKAGENT_EMAIL"),
                        "password": os.getenv("EMAILCHECKAGENT_PASSWORD"),
                        "report_to": os.getenv("EMAILCHECKAGENT_REPORT_TO", "mailman-1"),
                        "interval": int(os.getenv("EMAILCHECKAGENT_INTERVAL", 60))
                    }
                },
                {
                    "permanent_id": "mirror-9",
                    "name": "filesystem_mirror",
                    "filesystem": {
                        "folders": [
                            {"name": "payload", "type": "d"}
                        ]
                    },
                    "config": {
                        "watch_path": "/etc",
                        "mode": "once",
                        "self_destruct": True,
                        "report_to": "mailman-1"
                    }
                }
                ,
                {
                    "permanent_id": "email-send-1",
                    "name": "email_send",
                    "filesystem": {
                        "folders": [
                            {"name": "payload", "type": "d", "content": None}
                        ]
                    },
                    "config": {
                        "smtp_host": os.getenv("EMAILSENDAGENT_SMTP_HOST"),
                        "smtp_port": os.getenv("EMAILSENDAGENT_SMTP_PORT"),
                        "email": os.getenv("EMAILSENDAGENT_SMTP_EMAIL"),
                        "password": os.getenv("EMAILSENDAGENT_PASSWORD")
                    }
                },
                {
                    "permanent_id": "worker-backup-2",
                    "name": "worker",
                    "directives": {
                        "do something": ["sentinel-root"],
                        "do something else": ["something else"]
                    },
                    "children": [
                              {
                                "permanent_id": "logger-1",
                                "name": "logger",
                                "children": [
                                  {
                                    "permanent_id": "logger-2",
                                    "name": "logger",
                                    "children": [
                                      {
                                        "permanent_id": "logger-3",
                                        "name": "logger",
                                        "children": [
                                          {
                                            "permanent_id": "logger-4",
                                            "name": "logger",
                                            "children": [
                                                {
                                                    "permanent_id": "commander-1",
                                                    "name": "commander",
                                                    "children": []
                                                },
                                                {
                                                    "permanent_id": "worker-backup-3",
                                                    "name": "worker",
                                                    "children": []
                                                }
                                            ]
                                          }
                                        ]
                                      }
                                    ]
                                  }
                                ]
                              }
                            ]
                }
        ]
    }

    # Short Circuit matrix_directive above
    matrix_directive = {
        "permanent_id": 'matrix',
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
                "permanent_id": "matrix-https",
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
                    "permanent_id": "telegram-relay-1",
                    "name": "telegram_relay",
                    "config": {
                        "bot_token": os.getenv("TELEGRAM_API_KEY"),
                        "chat_id": os.getenv("TELEGRAM_CHAT_ID")
                    },
                    "children": []

                },
                {
                    "permanent_id": "mailman-1",
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
                    "permanent_id": "commander-1",
                    "name": "commander",
                    "children": [
                        {
                            "permanent_id": "commander-2",
                            "name": "commander",
                            "children": []
                        },
                    ]
                },
                {
                    "permanent_id": "oracle-1",
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
                    "permanent_id": "pinger-1",
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
                    "permanent_id": "metric-1",
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
                    "permanent_id": "scraper-1",
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
                    "permanent_id": "discord-relay-1",
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

    #Short Circuit matrix_directive above
    matrix_directive = {
        "permanent_id": 'matrix',
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
                "permanent_id": "matrix-https",
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
                "permanent_id": "mailman-1",
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
                "permanent_id": "discord-relay-1",
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
            {
                "permanent_id": "commander-1",
                "name": "commander",
                "children": [
                    {
                        "permanent_id": "commander-2",
                        "name": "commander",
                        "children": [
                              {
                                "permanent_id": "logger-1",
                                "name": "logger",
                                "children": [
                                  {
                                    "permanent_id": "logger-2",
                                    "name": "logger",
                                    "children": [
                                      {
                                        "permanent_id": "logger-3",
                                        "name": "logger",
                                        "children": [
                                          {
                                            "permanent_id": "logger-4",
                                            "name": "logger",
                                            "children": [
                                                {
                                                    "permanent_id": "commander-1",
                                                    "name": "commander",
                                                    "children": []
                                                },
                                                {
                                                    "permanent_id": "worker-backup-3",
                                                    "name": "worker",
                                                    "children": []
                                                },
                                                {
                                                    "permanent_id": "email-check-1",
                                                    "name": "email_check",
                                                    "filesystem": {
                                                        "folders": [
                                                            {"name": "payload", "type": "d", "content": None}
                                                        ]
                                                    },
                                                    "config": {
                                                        "imap_host": os.getenv("EMAILCHECKAGENT_IMAP_HOST"),
                                                        "email": os.getenv("EMAILCHECKAGENT_EMAIL"),
                                                        "password": os.getenv("EMAILCHECKAGENT_PASSWORD"),
                                                        "report_to": os.getenv("EMAILCHECKAGENT_REPORT_TO",
                                                                               "mailman-1"),
                                                        "interval": int(os.getenv("EMAILCHECKAGENT_INTERVAL", 60))
                                                    }
                                                },
                                            ]
                                          }
                                        ]
                                      }
                                    ]
                                  }
                                ]
                              }
                            ]
                    },
                ]
            },
            {
                "permanent_id": "calendar-agent-1",
                "name": "google_calendar",
                "config": {
                    "calendar_id": "primary",
                    "interval": 300,
                    "watch_ahead_minutes": 15,
                    "broadcast_to": ["mailman-1", "discord-relay-1"]
                },
                "filesystem": {
                    "folders": [{"name": "incoming", "type": "d"}]
                }
            }

        ]
    }

    # INSERT AGENT COMMAND
    if "--spawn-agent" in sys.argv:
        try:
            name_idx = sys.argv.index("-n")
            pid_idx = sys.argv.index("-pid")
            targ_idx = sys.argv.index("-targ")

            agent_name = sys.argv[name_idx + 1]
            new_perm_id = sys.argv[pid_idx + 1]
            target_perm_id = sys.argv[targ_idx + 1]

        except Exception as e:
            print(f"[BOOTLOADER][ERROR] Invalid agent insert syntax: {e}")
            sys.exit(1)

        print(f"[BOOTLOADER] Sending insert request for agent {new_perm_id} ({agent_name}) under {target_perm_id}")

        payload_dir = os.path.join("comm", "matrix", "payload")
        os.makedirs(payload_dir, exist_ok=True)

        inject_payload = {
            "type": "inject",
            "content": {
                "perm_id": new_perm_id,
                "agent_name": agent_name,
                "target_perm_id": target_perm_id,
                "filesystem": {
                    "folders": [{"name": "payload", "type": "d", "content": None}]
                },
                "children": []
            }
        }

        timestamp = int(time.time())
        payload_file = os.path.join(payload_dir, f"inject_{new_perm_id}_{timestamp}.json")

        with open(payload_file, "w") as f:
            json.dump(inject_payload, f, indent=2)

        print(f"[BOOTLOADER] Inject payload written: {payload_file}")
        print(f"[BOOTLOADER] Matrix will handle spawn and memory update.")
        sys.exit(0)

    # TARGETED KILL REQUEST
    if "--kill-perm_id" in sys.argv:
        idx = sys.argv.index("--kill-perm_id")
        if idx + 1 >= len(sys.argv):
            print("[BOOTLOADER][ERROR] Missing permanent_id after --kill-perm_id")
            sys.exit(1)

        target_perm_id = sys.argv[idx + 1]

        print(f"[BOOTLOADER] Sending kill request for {target_perm_id} to Matrix...")

        payload_dir = os.path.join("comm", "matrix", "payload")
        os.makedirs(payload_dir, exist_ok=True)

        kill_payload = {
            "type": "kill",
            "content": {
                "target": target_perm_id
            }
        }

        timestamp = int(time.time())
        payload_file = os.path.join(payload_dir, f"kill_{target_perm_id}_{timestamp}.json")

        with open(payload_file, "w") as f:
            json.dump(kill_payload, f, indent=2)

        print(f"[BOOTLOADER] Kill payload written: {payload_file}")
        print(f"[BOOTLOADER] Matrix will handle kill. Operation may take several minutes.")
        sys.exit(0)


    #IS THIS A TEAR DOWN
    if "--kill" in sys.argv:

        reaper = Reaper('pod', 'comm', 60)
        reaper.reap_all()
        print("[BOOTLOADER] Kill switch triggered. Swarm shutdown complete.")
        sys.exit(0)

    ###### kill all running processes under pod/ then smoke the directories
    elif hard_reset:

        #this makes sure if any agents are running they close before we nuke the pod directory
        reaper = Reaper('pod', 'comm')

        reaper.reap_all()

        cp.reset_hard()

        tp=TreeParser({})

        comm_file_spec=[
            {
                'name': 'agent_tree_master.json',
                'type': 'f',
                'atomic': True,
                'content': tp.load_dict(matrix_directive)
            },
            {
                'name': 'hello.moto',
                'type': 'd',
                'content': None

            },
            {
                'name': 'incoming',
                'type': 'd',
                'content': None

            },
            {"name": "payload", "type": "d", "content": None}

        ]

        #v=PermanentIdExtract.get_dict_by_permanent_id(matrix_directive, MATRIX_UUID)
        #print(v)
        #exit(0)

        json_string = json.dumps(matrix_directive, indent=4)

        cp.ensure_comm_channel(MATRIX_UUID, comm_file_spec, matrix_directive)
        new_uuid, pod_path = cp.create_runtime(MATRIX_UUID)
        cp.spawn_agent(UNIVERSE_ID, new_uuid, MATRIX_UUID, MATRIX_UUID, BOOTLOADER_UUID)

    else:
        cp.verify_soft()




 #   matrix = MatrixAgent(MATRIX_UUID, matrix_directive)
 #   matrix.label = f"matrix:{MATRIX_UUID}"  # ✅ This is the missing link
 #   matrix.boot()

  #  try:
  #      while True:
  #          pass
  #  except KeyboardInterrupt:
  #      matrix.shutdown()

if __name__ == "__main__":
    boot()
