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
            "universal_id": "sgt-in-arms",
            "name": "capital_gpt",
            "app": "blackhole-cometh",
            "config": {
                "role": "strategist",
                "mission": {

                    "initial_prompt": "You are a cyber-intelligence strategist inside a secure AI swarm.\n"
                                      "Simulate a system posture analysis. Your exploring a Rocky 9 Linux environment. \n"
                                      "Identify which processes are taking the most resources \n"
                                      "Classify them as suggestion, concern, or critical. \n"
                                      "Note: this is a production server, running apache, mysql, and redis server. \n"
                                      "Your response should be strategic, confident, and operationally useful; \n"
                                      "must be a flat dictionary with numeric string keys, where each value is a fully \n"
                                      "executable Linux shell command that can be used to test the server (e.g., no vague suggestions or descriptions). \n"
                                      "If your analysis is complete, return `exit_code: 2` with a summary and no further commands. Thank You. \n"
                                      ,


                    "system_constraints":
                                        "⚠️ OPERATIONAL CONSTRAINTS:\n"
                                        "- If you repeat any command you've already returned, stop the mission with exit_code: 3. \n"
                                        "- You are expected to remember the last 2 commands and stop if you suggest them again. \n"
                                        "- Do NOT include pseudo-commands or implementation ideas.\n"
                                        "- Do NOT return commands that will modify the system (install, remove, chown, chmod, rm).\n"
                                        "- Do NOT attempt to fix services (e.g., start, stop, restart, enable).\n"
                                        "- Do NOT alter file ownership or permissions.\n"
                                        "- Only include shell-safe commands that gather information.\n"
                                        "- If you believe the next command may escalate beyond safe observation (e.g., may alter system state, kill processes, or act on invalid/missing targets), do not proceed.\n"
                                        "- If the previous command output is a repeat, or you're parsing comments or redundant values (e.g. config directives already seen), respond with `exit_code: 3` and halt further analysis.\n"
                                        "- Do not proceed with follow-up grep commands for previously parsed keywords.\n"
                                        "- If it is warrented to continue analyse return `exit_code: 1`. \n"
                                        "- If your assessment is complete, return exit_code: 2. Do not continue with additional Linux commands.\n"


                            ,
                    "mission_id": "blackhole-cometh",
                    "response_mode": "verbose"

                }

            }
            ,
            "children": [

                        {
                          "universal_id": "discord-delta",
                          "name": "discord",
                          "app": "blackhole-cometh",
                          "filesystem": {
                            "folders": []
                          },
                          "config": {
                            "bot_token": os.getenv("DISCORD_TOKEN"),
                            "channel_id": os.getenv("DISCORD_CHANNEL_ID"),
                            "role": "comm",

                          }
                        },
                        {
                          "universal_id": "telegram-bot-father",
                          "name": "telegram_relay",
                          "app": "blackhole-cometh",
                          "filesystem": {
                            "folders": []
                          },
                          "config": {
                            "bot_token": os.getenv("TELEGRAM_API_KEY"),
                            "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
                            "role": "comm",

                          }
                        },
                        {
                            "universal_id": "golden-child-4",
                            "name": "oracle",
                            "app": "blackhole-cometh",
                            "filesystem": {
                                "folders": [],
                                "files": {}
                            },
                            "children": [],
                            "config": {
                                "role": "oracle",
                                "api_key": os.getenv("OPENAI_API_KEY_2"),
                            }

                        },
                        {
                            "universal_id": "arch-angel-destiny",
                            "name": "linux_scout",
                            "app": "blackhole-cometh",
                            "filesystem": {
                                "folders": [],
                                "files": {}
                            },
                            "children": [],
                            "config": {
                                "role": "scout"
                            }

                        },
                        
            ]
        }

    ]
}
