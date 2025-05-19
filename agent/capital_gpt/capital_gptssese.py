# ======== 🧠 CAPITAL_GPT: MISSION STRATEGIST ========
# One mission. One mind. No mercy.

# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
# ======== 🛬 LANDING ZONE END 🛬 ========"

# ======== 🧠 CAPITAL_GPT: MISSION STRATEGIST ========
# One mission. One mind. No mercy.
#
# ┌────────────────────────────────────────────┐
# │ General’s Comment Markup & Strategic Notes │
# └────────────────────────────────────────────┘
#
# This file is the sacred mind of capital_gpt. If you’re reading this,
# it means the strategist is being tuned. Leave breadcrumbs, monologues,
# or Socratic reflections here — your future self will thank you.
#
# ▪ PROMPT: Add new mission parsing format? Extend scan_inbox() and msg_launch_mission()
# ▪ PROMPT: Inject blank agents live via reflex with msg_spawn_blank()
# ▪ PROMPT: Boot mission via reflex or .msg drop, like a warlord

import os
import json
import time
from datetime import datetime
from core.boot_agent import BootAgent

class Agent(BootAgent):
    def __init__(self, path_resolution, command_line_args, tree_node):
        super().__init__(path_resolution, command_line_args, tree_node)
        self.mission_root = os.path.join(self.path_resolution["comm_path_resolved"], "queue")
        self.inbox = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
        self.state_path = os.path.join(self.path_resolution["comm_path_resolved"], "state.json")
        self.matrix_payload = os.path.join(self.path_resolution["comm_path"], "matrix", "payload")
        os.makedirs(self.inbox, exist_ok=True)
        os.makedirs(self.mission_root, exist_ok=True)
        os.makedirs(self.matrix_payload, exist_ok=True)
        self.trace_rounds=0

    def worker_pre(self):
        self.log("[CAPITAL] Pre-mission reflex initialized.")

        config = self.tree_node.get("config", {})
        mission_conf = config.get("mission", {})

        #msg["tracer_session_id"] = tracer_id
        #msg["packet_id"] = packet_num

        initial_prompt = config.get("initial_prompt") or mission_conf.get("initial_prompt")
        system_message = config.get("system_message") or mission_conf.get("system_message")
        mission_id = mission_conf.get("mission_id", "spin-a")

        if initial_prompt:
            self.route_structured_prompt_to_oracle(
                intent_text=initial_prompt,
                mission_id=mission_id,
                role="oracle",
                system_message_override=system_message
            )
            self.log("[CAPITAL] Initial prompt deployed to Oracle.")
        else:
            self.log("[CAPITAL] No initial prompt found in config.")

    def generate_query_id(self):
        return f"q_{int(time.time())}_{os.getpid()}"

    def worrker(self):
        try:

            self.log("[CAPITAL] Executing single-pass mission scan...")
            self.scan_inbox()

            # 🧠 REFLEX MEMORY: Check if there's a mission plan in state
            if os.path.exists(self.state_path):
                with open(self.state_path) as f:
                    state = json.load(f)

                mission_id = state.get("active_mission")
                if mission_id:
                    # Path to the mission folder
                    latest = sorted(os.listdir(self.mission_root), reverse=True)
                    for folder in latest:
                        if mission_id in folder:
                            mission_path = os.path.join(self.mission_root, folder)
                            break
                    else:
                        mission_path = None

                    if mission_path:
                        meta_path = os.path.join(mission_path, "meta.json")
                        if os.path.exists(meta_path):
                            with open(meta_path) as f:
                                meta = json.load(f)

                            progress = meta.get("status", "issued")
                            if progress != "complete":
                                self.log(f"[CAPITAL] Mission '{mission_id}' still active. Assessing state...")
                            else:
                                self.log(f"[CAPITAL] Mission '{mission_id}' marked complete.")

        except Exception as e:
            self.log(f"[CRITICAL][WORKER] Unhandled exception: {e}")

    def scan_inbox(self):
        if not os.path.exists(self.inbox):
            return

        for fname in os.listdir(self.inbox):
            if not fname.endswith(".msg"):
                continue

            fpath = os.path.join(self.inbox, fname)
            try:
                with open(fpath) as f:
                    msg = json.load(f)
                mission_type = msg.get("type")
                content = msg.get("content", {})

                if mission_type == "launch_mission":
                    self.handle_mission_launch(content, fname, msg)
                elif mission_type == "deploy_team":
                    self.handle_team_deploy(content, fname, msg)
                elif mission_type == "spawn_blank":
                    self.spawn_blank_agent(content, fname)
                elif mission_type == "mission_closure":
                    self.log(f"[CAPITAL] Received mission closure report: {content.get('mission_id')}")
                    self.mark_mission_state("complete", query_id=content.get("mission_id"))
                    # Optional: send email, Slack, or write final report file
                else:
                    self.log(f"[CAPITAL][IGNORED] Unknown message type in {fname}")

                os.remove(fpath)
            except Exception as e:
                self.log(f"[CAPITAL][ERROR] Failed to process {fname}: {e}")

    def route_structured_prompt_to_oracle(self, intent_text, mission_id=None, role="oracle",
                                          system_message_override=None):
        qid = self.generate_query_id()
        mission_id = mission_id or self.get_current_mission_id()

        self.log("[REROUTE] Waiting 3 seconds before sending Oracle a new prompt...")
        time.sleep(3)

        # msg["tracer_session_id"] = tracer_id
        # msg["packet_id"] = packet_num

        prompt_payload = {
            "query_id": qid,
            "prompt": intent_text,
            "target_universal_id": self.command_line_args.get("universal_id"),
            "role": role,
            "mission_id": mission_id,
            "tracer_session_id": 'GaXRBS1KU3zGoOmJoh91',
            "packet_id": int(time.time()),
            "report_final_packet_to": self.command_line_args.get("universal_id"),
        }

        if system_message_override:
            prompt_payload["system_message"] = system_message_override

        self.save_to_trace_session(prompt_payload, msg_type="msg")

        self.trace_rounds += 1
        if self.trace_rounds >= 20:

            self.confirm_with_human(qid)

        else:

            uid = self.get_node_by_role("oracle")["universal_id"]
            inbox = os.path.join(self.path_resolution["comm_path"], uid, "incoming")
            os.makedirs(inbox, exist_ok=True)
            fname = f"prompt_{qid}.prompt"
            with open(os.path.join(inbox, fname), "w") as f:
                json.dump(prompt_payload, f, indent=2)

        # Save to dialogue folder
        dialogue_path = self.get_dialogue_path(mission_id)
        os.makedirs(dialogue_path, exist_ok=True)
        with open(os.path.join(dialogue_path, f"{qid}.prompt"), "w") as f:
            json.dump(prompt_payload, f, indent=2)

        self.log(f"[INTEL] Routed structured prompt {qid} with mission_id {mission_id} to oracle.")


    def append_to_thread(self, query_id, role, type, content):
        thread_path = os.path.join(self.get_dialogue_path(self.get_current_mission_id()), f"thread_{query_id}.jsonl")
        os.makedirs(os.path.dirname(thread_path), exist_ok=True)
        line = {
            "role": role,
            "type": type,
            "query_id": query_id,
            "content": content
        }
        with open(thread_path, "a") as f:
            f.write(json.dumps(line) + "\n")
        self.log(f"[THREAD] Appended {type} from {role} to thread: {query_id}")

    def msg_gpt_analysis(self, content, packet):
        qid = packet.get("query_id")
        summary = content.get("summary", "").strip()
        self.append_to_thread(qid, role="oracle", type="gpt_response", content=content)

        mission_status = content.get("mission_status")
        if mission_status == 0:
            self.log("[CAPITAL] Oracle marked mission complete.")
            return
        if mission_status == -1:
            self.log("[CAPITAL][ERROR] Oracle encountered a failure. Mission paused. Operator intervention needed.")
            return

        # Optional delay before routing to scout
        time.sleep(2)

        rrp_code = "1"
        if "RRP:" in summary:
            rrp_code = summary.split("RRP:")[1].strip().split()[0]

        tracer_session_id = packet.get("tracer_session_id", "unknown")
        packet_id = packet.get("packet_id", 1)

        try:
            response = json.loads(summary)
            exit_code = response.get("exit_code", 0)

            if exit_code == 1:
                for step in response.get("actions", []):
                    command = step.get("command")
                    if command:
                        self.dispatch_to_scout(qid, command, tracer_session_id, self.get_next_packet_id())
            elif exit_code == 0:
                self.mark_mission_complete(qid, tracer_session_id)
            elif exit_code == 3:
                self.alert_operator(qid, tracer_session_id)
            else:
                self.fail_safe_stop(qid, tracer_session_id, reason="Unhandled exit code")
        except json.JSONDecodeError:
            self.fail_safe_stop(qid, tracer_session_id, reason="Invalid GPT JSON format")

        if rrp_code == "3":
            self.mark_mission_state("paused", qid)
        elif rrp_code == "2":
            self.log("[CAPITAL] RRP: 2 — optional response. No reroute.")
        elif rrp_code == "1":
            self.reroute_back_to_oracle(qid)




    def mark_mission_state(self, state, query_id=None):
        if not os.path.exists(self.state_path):
            self.log("[CAPITAL] Cannot mark mission state: state.json missing.")
            return

        try:
            with open(self.state_path, "r") as f:
                state_data = json.load(f)

            state_data["status"] = state
            if query_id:
                state_data["last_query"] = query_id

            with open(self.state_path, "w") as f:
                json.dump(state_data, f, indent=2)

            self.log(f"[CAPITAL] Mission state updated to: {state}")
        except Exception as e:
            self.log(f"[CAPITAL][ERROR] Failed to update mission state: {e}")

    def dispatch_to_scout(self, qid, command, tracer_session_id="unknown", packet_id=1):
        scout_uid = self.get_node_by_role("scout")["universal_id"]
        msg = {
            "type": "check",
            "query_id": qid,
            "check": command,
            "reflex_id": self.command_line_args.get("universal_id"),
            "tracer_session_id": tracer_session_id,
            "packet_id": int(time.time())
        }


        scout_inbox = os.path.join(self.path_resolution["comm_path"], scout_uid, "incoming")
        os.makedirs(scout_inbox, exist_ok=True)
        with open(os.path.join(scout_inbox, f"{qid}.msg"), "w") as f:
            json.dump(msg, f, indent=2)
        self.log(f"[CAPITAL] Dispatched command to linux_scout: {command}")

    def reroute_back_to_oracle(self, query_id):
        thread_path = os.path.join(self.get_dialogue_path(self.get_current_mission_id()), f"thread_{query_id}.jsonl")
        if not os.path.exists(thread_path):
            self.log(f"[CAPITAL][ERROR] No thread found for {query_id}")
            return

        with open(thread_path) as f:
            lines = f.readlines()

        history = []
        for line in lines:
            try:
                entry = json.loads(line)
                role = entry.get("role", "user")
                content = entry.get("content", {})
                if isinstance(content, dict):
                    msg = content.get("summary") or json.dumps(content)
                else:
                    msg = str(content)
                history.append(f"{role.upper()}: {msg}")
            except:
                continue

        prompt_text = "\n".join(history[-8:])  # last 8 turns
        self.route_structured_prompt_to_oracle(
            intent_text=prompt_text,
            mission_id=self.get_current_mission_id(),
            role="oracle",
            system_message_override="Continue the diagnostic conversation using prior messages. Suggest what command or investigation should be done next."
        )

    def msg_scan_cycle(self, content, packet):
        qid = packet.get("query_id")
        if not qid:
            self.log("[CAPITAL][ERROR] scan_cycle msg missing query_id.")
            return
        self.append_to_thread(qid, role="linux_scout", type="scan_result", content=content)

        # 🧠 Check if more is needed
        command = content.get("command", "")
        status = content.get("status", "")

        # Trigger reroute if:
        # - a command was run
        # - or status = success
        # - or output exists
        if command or status == "success" or content.get("output"):
            self.reroute_back_to_oracle(qid)
        else:
            self.log(f"[CAPITAL] Scout returned nothing actionable for {qid}.")

    def msg_launch_mission(self, content, packet):
        fname = f"reflex_{content.get('mission', 'unknown')}.msg"
        self.handle_mission_launch(content, fname, packet)

    def msg_deploy_team(self, content, packet):
        fname = f"reflex_team_{content.get('team', 'unknown')}.msg"
        self.handle_team_deploy(content, fname, packet)

    def msg_spawn_blank(self, content, packet):
        fname = f"reflex_blank_{content.get('universal_id', 'unnamed')}.msg"
        self.spawn_blank_agent(content, fname)

    def get_current_mission_id(self):
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                state = json.load(f)
            return state.get("active_mission", "unknown")
        return "unknown"

    def get_dialogue_path(self, mission_id):
        for folder in sorted(os.listdir(self.mission_root), reverse=True):
            if mission_id in folder:
                return os.path.join(self.mission_root, folder, "dialogue")
        return os.path.join(self.mission_root, f"unknown_mission_{mission_id}", "dialogue")



    def handle_mission_launch(self, content, fname, raw_msg):
        mission = content.get("mission")
        if not mission:
            self.log(f"[CAPITAL][ERROR] Missing mission name in {fname}")
            return

        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                state = json.load(f)
            if state.get("active_mission") and not self.override_flag():
                self.log(f"[CAPITAL][REJECTED] Another mission already active: {state['active_mission']}")
                self.reject_mission(fname, raw_msg)
                return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        mission_folder = os.path.join(self.mission_root, f"{ts}_{mission}")
        os.makedirs(mission_folder, exist_ok=True)

        self.write_file(mission_folder, "received.msg", raw_msg)

        cmd = f"python3 site_ops/site_boot.py --universe {mission} --directive {mission}"
        self.write_file(mission_folder, "issued.cmd", cmd, is_text=True)

        reversal = f"python3 site_ops/site_kill.py --universe {mission}"
        self.write_file(mission_folder, "reversal.cmd", reversal, is_text=True)

        meta = {
            "mission": mission,
            "mode": "launch_mission",
            "status": "issued",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "agents": ["capital_gpt"]
        }
        self.write_file(mission_folder, "meta.json", meta)

        self.write_file(mission_folder, "mission.md", self.generate_markdown_brief(mission, cmd, reversal, meta), is_text=True)

        with open(self.state_path, "w") as f:
            json.dump({
                "active_mission": mission,
                "started": meta["timestamp"]
            }, f, indent=2)

        self.log(f"[CAPITAL] Launched mission '{mission}'. Logs written to {mission_folder}")

    def handle_team_deploy(self, content, fname, raw_msg):
        team = content.get("team")
        target = content.get("target_universal_id")
        if not team or not target:
            self.log(f"[CAPITAL][ERROR] Missing target or team in {fname}")
            return

        cmd = {
            "type": "inject_team",
            "timestamp": time.time(),
            "content": {
                "target_universal_id": target,
                "subtree": f"teams/{team}.json"
            }
        }
        outfile = os.path.join(self.matrix_payload, f"deploy_team_{int(time.time())}.json")
        with open(outfile, "w") as f:
            json.dump(cmd, f, indent=2)

        self.log(f"[CAPITAL] Deployed team '{team}' under {target}.")

    def spawn_blank_agent(self, content, fname):
        agent_id = content.get("universal_id")
        agent_name = content.get("name", "blank")
        config = content.get("config", {})

        if not agent_id:
            self.log(f"[CAPITAL][ERROR] Missing universal_id in {fname}")
            return

        cmd = {
            "type": "inject",
            "timestamp": int(time.time()),
            "content": {
                "target_universal_id": self.command_line_args.get("universal_id", "unknown"),
                "universal_id": agent_id,
                "agent_name": agent_name,
                "config": config,
                "delegated": [],
                "filesystem": {}
            }
        }

        outfile = os.path.join(self.matrix_payload, f"spawn_blank_{agent_id}.json")
        with open(outfile, "w") as f:
            json.dump(cmd, f, indent=2)

        self.log(f"[CAPITAL] Spawned blank agent '{agent_id}' → Matrix")

    def override_flag(self):
        return os.path.exists(os.path.join(self.inbox, "override.flag"))

    def reject_mission(self, fname, msg):
        reject_dir = os.path.join(self.inbox, "rejected")
        os.makedirs(reject_dir, exist_ok=True)
        with open(os.path.join(reject_dir, fname), "w") as f:
            json.dump(msg, f, indent=2)

    def write_file(self, folder, name, data, is_text=False):
        path = os.path.join(folder, name)
        with open(path, "w") as f:
            if is_text:
                f.write(data)
            else:
                json.dump(data, f, indent=2)

    def generate_markdown_brief(self, mission, cmd, reversal, meta):
        return f"""# 🧠 MISSION BRIEF: {mission}

- **Mission ID:** {meta['mission']}
- **Timestamp:** {meta['timestamp']}
- **Issued By:** capital_gpt
- **Launch Mode:** {meta['mode']}
- **Directive Path:** boot_directives/{mission}.py
- **Reversal Path:** {reversal}

## 🎯 Objective
Autonomous launch of '{mission}' and full operational briefing tracking.

## 🛠 Deployment Log
```
{cmd}
```

## 🔁 Reversal
```
{reversal}
```

---
**Mission logged by capital_gpt.**
"""

if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()
