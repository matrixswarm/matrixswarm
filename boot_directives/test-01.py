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

        ]
    }
