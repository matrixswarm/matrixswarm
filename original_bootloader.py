from dotenv import load_dotenv
import os
import sys
import time
import json
import argparse
from agent.core.path_manager import PathManager
from agent.core.core_spawner import CoreSpawner
from agent.core.tree_parser import TreeParser
from agent.core.class_lib.processes.reaper import Reaper
from agent.core.swarm_session_root import SwarmSessionRoot

load_dotenv()

# Parse CLI arguments
parser = argparse.ArgumentParser()
parser.add_argument("--kill", action="store_true", help="Kill all agents in current or given path")
parser.add_argument("-p", "--path", type=str, help="Manually specify swarm root")
parser.add_argument("--list-universes", action="store_true", help="List all known universes + reboots")
args = parser.parse_args()

# List all universes
if args.list_universes:
    base = "/matrix"
    if not os.path.exists(base):
        print("[LIST] No matrix directory found.")
        sys.exit(0)

    for universe in os.listdir(base):
        uni_path = os.path.join(base, universe)
        if not os.path.isdir(uni_path):
            continue

        print(f"\n🌌 Universe: {universe}")
        for session in sorted(os.listdir(uni_path)):
            path = os.path.join(uni_path, session)
            if os.path.isdir(path) and session != "latest":
                print(f"  └─ {session}")
    sys.exit(0)

# Setup session from override or SwarmSessionRoot
if args.path:
    swarm_root = args.path
    pod_path = os.path.join(swarm_root, "pod")
    comm_path = os.path.join(swarm_root, "comm")
    agent_path = os.environ.get("AGENT_PATH", "/sites/orbit/python/agent")
    print(f"[BOOTLOADER] Manually overriding session: {swarm_root}")
else:
    pm = PathManager(use_session_root=True)
    cp = CoreSpawner(path_manager=pm)
    session = SwarmSessionRoot()
    UNIVERSE_ID = session.universe_id
    REBOOT_UUID = session.reboot_uuid
    pod_path = pm.get_path("pod", trailing_slash=False)
    comm_path = pm.get_path("comm", trailing_slash=False)
    agent_path = pm.get_path("agent", trailing_slash=False)

session = SwarmSessionRoot()
UNIVERSE_ID = session.universe_id
REBOOT_UUID = session.reboot_uuid

MATRIX_UUID = "matrix"
BOOTLOADER_UUID = "bootloader"

print(f"[BOOTLOADER] 🧠 UNIVERSE_ID={UNIVERSE_ID}, REBOOT_UUID={REBOOT_UUID}")

print("[BOOTLOADER] PathManager Session Paths:")
for k, v in pm.list_paths().items():
    print(f"  {k}: {v}")


#print(pm.construct_path("agent",str(uuid.uuid4()),'notify'))
#exit()

def boot():
    #encryption_key = load_or_create_key()
    #core = ProtectedCore(encryption_key)

    hard_reset = True

    matrix_directive = {
        "universal_id": 'matrix',
        "children": [

                {
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
                    "universal_id": "commander-2",
                    "name": "commander",
                    "children": []
                },
                {
                    "universal_id": "email-check-1",
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
                    "universal_id": "mirror-9",
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
                    "universal_id": "email-send-1",
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
                    "universal_id": "worker-backup-2",
                    "name": "worker",
                    "directives": {
                        "do something": ["sentinel-root"],
                        "do something else": ["something else"]
                    },
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
                                                    "universal_id": "commander-1",
                                                    "name": "commander",
                                                    "children": []
                                                },
                                                {
                                                    "universal_id": "worker-backup-3",
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


        ]
    }

    matrix_directisve = {
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
            {
                "universal_id": "commander-1",
                "name": "commander",
                "app": "matrix-core",
                "children": []

            },
                ]
    }


    # INSERT AGENT COMMAND
    if "--spawn-agent" in sys.argv:
        try:
            name_idx = sys.argv.index("-n")
            pid_idx = sys.argv.index("-pid")
            targ_idx = sys.argv.index("-targ")

            agent_name = sys.argv[name_idx + 1]
            new_universal_id = sys.argv[pid_idx + 1]
            target_universal_id = sys.argv[targ_idx + 1]

        except Exception as e:
            print(f"[BOOTLOADER][ERROR] Invalid agent insert syntax: {e}")
            sys.exit(1)

        print(f"[BOOTLOADER] Sending insert request for agent {new_universal_id} ({agent_name}) under {target_universal_id}")

        payload_dir = os.path.join("comm", "matrix", "payload")
        os.makedirs(payload_dir, exist_ok=True)

        inject_payload = {
            "type": "inject",
            "content": {
                "universal_id": new_universal_id,
                "agent_name": agent_name,
                "target_universal_id": target_universal_id,
                "filesystem": {
                    "folders": [{"name": "payload", "type": "d", "content": None}]
                },
                "children": []
            }
        }

        timestamp = int(time.time())
        payload_file = os.path.join(payload_dir, f"inject_{new_universal_id}_{timestamp}.json")

        with open(payload_file, "w") as f:
            json.dump(inject_payload, f, indent=2)

        print(f"[BOOTLOADER] Inject payload written: {payload_file}")
        print(f"[BOOTLOADER] Matrix will handle spawn and memory update.")
        sys.exit(0)

    # TARGETED KILL REQUEST
    if "--kill-universal_id" in sys.argv:
        idx = sys.argv.index("--kill-universal_id")
        if idx + 1 >= len(sys.argv):
            print("[BOOTLOADER][ERROR] Missing universal_id after --kill-universal_id")
            sys.exit(1)

        target_universal_id = sys.argv[idx + 1]

        print(f"[BOOTLOADER] Sending kill request for {target_universal_id} to Matrix...")

        payload_dir = os.path.join("comm", "matrix", "payload")
        os.makedirs(payload_dir, exist_ok=True)

        kill_payload = {
            "type": "kill",
            "content": {
                "target": target_universal_id
            }
        }

        timestamp = int(time.time())
        payload_file = os.path.join(payload_dir, f"kill_{target_universal_id}_{timestamp}.json")

        with open(payload_file, "w") as f:
            json.dump(kill_payload, f, indent=2)

        print(f"[BOOTLOADER] Kill payload written: {payload_file}")
        print(f"[BOOTLOADER] Matrix will handle kill. Operation may take several minutes.")
        sys.exit(0)


    #IS THIS A TEAR DOWN
    if "--kill" in sys.argv:
        swarm_root = "/matrix/bb"
        sessions = [d for d in os.listdir(swarm_root) if os.path.isdir(os.path.join(swarm_root, d))]
        sessions = sorted(sessions)

        if not sessions:
            print("[KILL] No swarm sessions found.")
            sys.exit(1)

        print("\n🧠 Active Swarm Sessions:\n")
        for i, session in enumerate(sessions, 1):
            tag = " (last)" if i == len(sessions) else ""
            print(f"{i}.  {session}{tag}")

        choice = input("\nChoose a session number to kill [default: last]: ").strip()
        idx = int(choice) - 1 if choice else len(sessions) - 1
        chosen = sessions[idx]

        root = os.path.join(swarm_root, chosen)
        pod_path = os.path.join(root, "pod")
        comm_path = os.path.join(root, "comm")

        print(f"\n[KILL] Executing shutdown for: {chosen}")
        reaper = Reaper(
            pod_root=pod_path,
            comm_root=comm_path,
            timeout_sec=60
        )
        reaper.reap_all()

        print("[KILL] Reaper complete. Nuking directories...")

        for path in [pod_path, comm_path]:
            if os.path.exists(path):
                shutil.rmtree(path)
                print(f"[KILL] Deleted: {path}")

        print(f"[BOOTLOADER] Session {chosen} terminated.")
        sys.exit(0)

    ###### kill all running processes under pod/ then smoke the directories
    elif hard_reset:

        #this makes sure if any agents are running they close before we nuke the pod directory
        reaper = Reaper(
            pod_root=pm.get_path("pod", trailing_slash=False),
            comm_root=pm.get_path("comm", trailing_slash=False)
        )

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

        #v=PermanentIdExtract.get_dict_by_universal_id(matrix_directive, MATRIX_UUID)
        #print(v)
        #exit(0)
        matrix_without_children = {k: v for k, v in matrix_directive.items() if k != "children"}

        cp.ensure_comm_channel(MATRIX_UUID, comm_file_spec, matrix_directive)
        new_uuid, pod_path = cp.create_runtime(MATRIX_UUID)
        cp.spawn_agent(new_uuid, MATRIX_UUID, MATRIX_UUID, BOOTLOADER_UUID, matrix_without_children)

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
