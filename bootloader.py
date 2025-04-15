import sys
import os
import json
import uuid
from agent.core.path_manager import PathManager
from agent.core.core_spawner import CoreSpawner
#from agent.matrix.matrix import MatrixAgent

cp = CoreSpawner()

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
                "permanent_id": "commander-1",
                "name": "commander",
                "children": []
            }

                ,]
    }

    ###### kill all running processes under pod/ then smoke the directories
    if hard_reset:
        cp.reset_hard()

        comm_file_spec=[
            {
                'name': 'agent_tree_master.json',
                'type': 'f',
                'atomic': True,
                'content': matrix_directive
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
        cp.ensure_comm_channel(MATRIX_UUID, comm_file_spec, matrix_directive)
        new_uuid, pod_path = cp.create_runtime(MATRIX_UUID)
        cp.spawn_agent(UNIVERSE_ID, new_uuid, MATRIX_UUID, MATRIX_UUID, BOOTLOADER_UUID)
        print('go time!')
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
