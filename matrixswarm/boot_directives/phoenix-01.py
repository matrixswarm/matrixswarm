matrix_directive = {
        "universal_id": "matrix",
        "name": "matrix",
        "tags": {
          "packet_signing": {
            "in": True,
            "out": True
          }
        },

        "children": [# MATRIX PROTECTION LAYER 4 SENTINELS
        # 4th SENTINEL WATCHES MATRIX, REST WATCH SENTINEL IN FRONT
        # ONLY WAY TO KILL MATRIX WOULD BE TO KILL THEM ALL, TAKING ANY COMBO OF 4 OUT DOES NOTHING
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
            "tags": {
              "packet_signing": {
                "in": True,
                "out": True
              },
              "connection": {
                "proto": "https",
                "spki_pin_auth": True
              },
              "connection_cert": {
                "proto": "https"
              },
            },
            "config": {
              "service-manager": []
            }
          },

          {
            "universal_id": "websocket-relay",
            "name": "matrix_websocket",
            "tags": {
              "packet_signing": {
                "in": True,
                "out": True
              },
              "connection": {
                "proto": "wss",
                "spki_pin_auth": True
              },
              "config": {
                "allowlist_ips": [
                    # 'ip',
                    # 'ip2'
                ],
                "service-manager": [{
                    "role": ["hive.alert@cmd_send_alert_msg, hive.rpc@cmd_rpc_route, hive.log@cmd_stream_log"],
                    "scope": ["parent", "any"],  # who it serves
                    "priority": {  # lower = more preferred
                        "hive.log.delivery": -1,
                        "hive.proxy.route": 5,
                        "default": 10
                    },
                }],

            },
              "connection_cert": {
                "proto": "wss"
              },
            }
          },
          {
            "universal_id": "log_sentinel",
            "name": "log_sentinel",
            "config": {

                "service-manager": [{
                    "role": ["hive.log@cmd_stream_log"],
                    "scope": ["parent", "any"],  # who it serves
                    "priority": {  # lower = more preferred
                        "hive.log.delivery": -1,
                        "hive.proxy.route": 5,
                        "default": 10
                    },
                }],

            },
          }
        ]
      }