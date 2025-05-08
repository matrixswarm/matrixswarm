matrix_directive = {
        "universal_id": 'matrix',
        "name": "matrix",
        "filesystem": {
            "folders": [],
            "files": {}
        },

        "children": [
                {
                  "universal_id": "blank-agent-1",
                  "name": "blank_agent",
                  "config": {
                    "role": "observer",
                    "filesystem": {
                        "folders": [],
                        "files": {}
                    },
                    "factories": {
                      "alert.subscriber": {
                        "levels": ["info"],
                        "msg": "Hello, Matrix."
                      }
                    }
                  }
                }
            ],
}