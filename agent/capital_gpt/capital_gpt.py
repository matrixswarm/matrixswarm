# ======== 🧠 CAPITAL_GPT: MISSION STRATEGIST ========
# One mission. One mind. No mercy.

# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
# ======== 🛬 LANDING ZONE END 🛬 ========"

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
import subprocess
import traceback
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

        self.template = {
            "summary": "..",
            "actions": {"1": "...", "2": "...", "etc": "..."},
            "exit_code": 1
        }

        self.alert_fired = False
        self.trace_rounds = 0
        self.max_rounds = 5  # Failsafe to prevent infinite loops (Initialize here!)

    #INITIAL PROMPT
    def worker_pre(self):

        self.log("[CAPITAL] Pre-mission reflex initialized.")

        self.trace_rounds = 0
        self.alert_fired = False

        config = self.tree_node.get("config", {})
        mission_conf = config.get("mission", {})

        #msg["tracer_session_id"] = tracer_id
        #msg["packet_id"] = packet_num

        mission_id = mission_conf.get("mission_id", "spin-a")

        initial_prompt_text = mission_conf.get("initial_prompt", "")
        self.system_constraints = mission_conf.get("system_constraints", "")
        self.system_constraints = self.system_constraints + "- Please complete your assessment within " + str(self.max_rounds) + " rounds, you're currently at round "+str(self.trace_rounds+1)+"; summarize your findings at the last round or if you are forced to end early."

        initial_prompt_str = (
            f"{initial_prompt_text}\n\n"
            f"Respond in this JSON format; exit_code (0=need more information; 1=follow-up; 2=complete):\n"
            f"{json.dumps(self.template, indent=2)}"
        )


        self.route_structured_prompt_to_oracle(
            intent_text=initial_prompt_str,
            mission_id=mission_id,
            role="oracle",
            history=[]
        )
        self.log("[CAPITAL] Initial prompt deployed to Oracle.")

    def generate_query_id(self):
        return f"q_{int(time.time())}_{os.getpid()}"


    '''
          "type": "prompt",
          "query_id": "q_1747592257_2533059",
          "content": "{\"prompt\": \"You are a cyber-intelligence strategist inside a secure AI swarm. Simulate a system posture analysis. Your in a Rocky 9 Linux environment. Identify risks. Classify them as suggestion, concern, or critical. Your response should be strategic, confident, and operationally useful.\", \"history\": [], \"mission_id\": \"blackhole-cometh\", \"target_universal_id\": \"sgt-in-arms\"}",
          "role": "oracle",
          "tracer_session_id": "GaXRBS1KU3zGoOmJoh91",
          "packet_id": 1747592260,
          "report_final_packet_to": "sgt-in-arms",
          "system_message": "You are Oracle, the AI strategist of MatrixSwarm. The strategist has no active thoughts or system context. You must ask for exact shell commands to gather Linux system information so you can advise next steps."
    '''
    def route_structured_prompt_to_oracle(self, intent_text, mission_id=None, role="oracle", history=None):

        time.sleep(5)

        qid = self.generate_query_id()
        mission_id = mission_id or self.get_current_mission_id()

        self.log("[REROUTE] Waiting 3 seconds before sending Oracle a new prompt...")

        intent_text = (
                intent_text + "\n" +
                self.system_constraints + "\n" +
                "Respond in this JSON format:\n"
                "{\n  \"summary\": \"...\",\n  \"actions\": {\"1\": \"...\", \"2\": \"...\"},\n  \"exit_code\": 1\n}"
        )

        prompt_payload = {
            "type": "prompt",
            "query_id": qid,
            "tracer_session_id": 'GaXRBS1KU3zGoOmJoh91',
            "packet_id": int(time.time()),
            "target_universal_id": self.command_line_args.get("universal_id"),
            "report_final_packet_to": self.command_line_args.get("universal_id"),
            "role": role,
            "response_mode": "terse",
            "content": {
                "prompt": intent_text,
                "mission_id": mission_id,
                "history": []
            }
        }

        self.save_to_trace_session(prompt_payload, msg_type="msg")

        uid = self.get_node_by_role("oracle")["universal_id"]
        inbox = os.path.join(self.path_resolution["comm_path"], uid, "incoming")
        os.makedirs(inbox, exist_ok=True)
        fname = f"prompt_{qid}.msg"
        with open(os.path.join(inbox, fname), "w") as f:
            json.dump(prompt_payload, f, indent=2)

        dialogue_path = self.get_dialogue_path(mission_id)
        os.makedirs(dialogue_path, exist_ok=True)
        with open(os.path.join(dialogue_path, f"{qid}.prompt"), "w") as f:
            json.dump(prompt_payload, f, indent=2)

        self.log(f"[INTEL] Routed structured prompt {qid} with mission_id {mission_id} to oracle.")


    def append_to_thread(self, query_id, role, type, content):
        """
               Appends a new message entry to a dialogue thread file in JSON Lines format.

               Parameters:
                   query_id (str): Identifier for the current query/thread.
                   role (str): The role of the message sender (e.g., 'user', 'system', 'agent').
                   type (str): The type of the message (e.g., 'text', 'action', 'error').
                   content (str or dict): The actual content of the message.

               Behavior:
                   - Constructs the file path for the thread using the current mission and query ID.
                   - Ensures the directory structure exists.
                   - Formats the message into a JSON object and appends it to the corresponding .jsonl thread file.
                   - Logs the operation for debugging or tracking purposes.
               """
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

        response = content.get("response")

        qid = packet.get("query_id")

        self.append_to_thread(qid, role="oracle", type="gpt_response", content=response)

        mission_status = content.get("mission_status")
        if mission_status == 0:
            self.log("[CAPITAL] Oracle marked mission complete.")
            return
        if mission_status == -1:
            self.log("[CAPITAL][ERROR] Oracle encountered a failure. Mission paused. Operator intervention needed.")
            return

        tracer_session_id = content.get("tracer_session_id", "unknown")
        packet_id = content.get("packet_id", 1)

        try:
            # Extract relevant information
            if isinstance(response, str):
                try:
                    response_data = json.loads(response)
                except Exception as e:
                    self.log(f"[CAPITAL][ERROR] Failed to parse 'response' as JSON: {e}")
                    self.log(f"[CAPITAL][DEBUG] Raw response:\n{response}")
                    return
            else:
                response_data = response

            actions = response_data.get("actions", {})

            command_output = {}

            flat_actions = {}
            if isinstance(actions, dict):
                count = 1
                for key, value in actions.items():
                    if isinstance(value, dict) and "command" in value:
                        flat_actions[str(count)] = value["command"]
                        count += 1
                    elif isinstance(value, str):
                        flat_actions[str(count)] = value
                        count += 1
                    elif isinstance(value, list):
                        for cmd in value:
                            flat_actions[str(count)] = cmd
                            count += 1
                    else:
                        self.log(f"[CAPITAL][WARN] Unrecognized action format: {value}")

            # 🔓 Parse and assign
            summary = response_data.get("summary", "")
            actions = response_data.get("actions", {})
            exit_code = response_data.get("exit_code", 0)


            # 🔒 These are your final-stop conditions
            if exit_code == 0:
                if not self.alert_fired:
                    self.alert_operator(qid, message=f"🧹 Mission complete: {summary}")
                return

            elif exit_code == 2:
                self.log(f"[REFLEX] Oracle signaled complete analysis.")
                if not self.alert_fired:
                    self.alert_operator(qid, message=f"✅ Oracle signaled complete analysis: {summary}")
                return

            elif exit_code == 3:
                if not self.alert_fired:
                    self.alert_operator(qid, message=f"❌ Oracle signaled forced complete analysis: {summary}")
                return

            elif exit_code == -1:
                if not content.get("already_retried"):
                    self.log("[REFLEX] Oracle returned exit_code -1. Retrying once...")
                    content["already_retried"] = True
                    self.route_structured_prompt_to_oracle(
                        intent_text=self.build_next_prompt(response, {}),
                        mission_id=content.get('mission_id'),
                        role="oracle"
                    )
                    return
                else:
                    if not self.alert_fired:
                        self.alert_operator(qid, message="Oracle parse failed again. Alerting operator.")
                    return

            if exit_code == 1:
                self.trace_rounds += 1
                self.log(f"[REFLEX] Trace round: {self.trace_rounds} of {self.max_rounds}")

                if self.trace_rounds >= self.max_rounds:
                    if not self.alert_fired:
                        self.alert_operator(qid, message="🔚 Reflex loop reached max rounds.")
                        self.alert_fired = True
                    return

                if actions:
                    for key, command in flat_actions.items():
                        self.log(command)
                        command_output[key] = self.run_check(command)

                self.route_structured_prompt_to_oracle(
                    intent_text=self.build_next_prompt(response, command_output),
                    mission_id=content.get("mission_id"),
                    role="oracle"
                )

        except Exception as e:
            error_details = traceback.format_exc()
            self.log(f"[CAPITAL][ERROR] Error processing Oracle response: {e} -> {error_details}")

            #self.fail_safe_stop(qid, tracer_session_id, reason=f"Invalid GPT response format: {e}")

    def alert_operator(self, qid, message=None):

        if self.alert_fired:
            return

        self.alert_fired = True

        if message:
            msg = f"{message}"
        else:
            msg = f"🚨 ORACLE REFLEX TERMINATION\n\nReflex loop failed (exit_code = -1)"

        comms = self.get_nodes_by_role('comm')
        if not comms:
            self.log("[REFLEX][ALERT] No comm nodes found. Alert not dispatched.")
        else:
            for comm in comms:
                self.log(f"[REFLEX] Alert routed to comm agent: {comm['universal_id']}")
                self.drop_reflex_alert(msg, comm['universal_id'], level="critical", cause="[PARSE ERROR]")

    def drop_reflex_alert(self, message, agent_dir, level="critical", cause=""):
        """
        Drop a reflex alert .msg file into /incoming/<agent_dir>/ for comm relays to pick up.
        Respects factory-injected Discord/Telegram agents already listening.
        """

        msg_body = message if message else "[REFLEX] No message provided."
        formatted_msg = f"📣 Swarm Message\n{msg_body}"
        payload = {
            "type": "send_packet_incoming",
            "content": {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "universal_id": self.command_line_args.get("universal_id", "unknown"),
                "level": level,
                "msg": msg_body,
                "formatted_msg": formatted_msg,
                "cause": cause or msg_body,
                "origin": self.command_line_args.get("universal_id", "unknown")
            }
        }

        inbox_path = os.path.join(self.path_resolution["comm_path"], agent_dir, "incoming")
        os.makedirs(inbox_path, exist_ok=True)

        try:
            fname = f"reflex_alert_{int(time.time())}.msg"
            fullpath = os.path.join(inbox_path, fname)

            with open(fullpath, "w") as f:
                json.dump(payload, f)

            self.log(f"[REFLEX] Alert dropped to: {fullpath}")

        except Exception as e:
            self.log(f"[REFLEX][ERROR] Failed to write alert msg: {e}")



    def summarize_reflex_history(self, qid, limit=6):

        thread_path = os.path.join(self.get_dialogue_path(self.get_current_mission_id()), f"thread_{qid}.jsonl")

        if not os.path.exists(thread_path):
            return "[CAPITAL][ERROR] No thread log found."

        history = []
        with open(thread_path, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    role = entry.get("role", "unknown")
                    content = entry.get("content", {})
                    if isinstance(content, str):
                        content_str = content
                    elif isinstance(content, dict):
                        summary = content.get("summary")
                        actions = content.get("actions")
                        if summary and actions:
                            content_str = f"🧠 {summary}\n📜 Commands: " + ", ".join(actions.values())
                        else:
                            content_str = json.dumps(content)
                    else:
                        content_str = str(content)

                    history.append(f"{role.upper()} ➤ {content_str}")
                except Exception as e:
                    history.append(f"[ERROR] Could not parse entry: {e}")

        # Only return the last few cycles for readability
        return "\n\n".join(history[-limit:])


    def build_next_prompt(self, response, command_output) -> str:
        """
        Given Oracle's last JSON response and your Linux command output,
        build the next prompt to send back to Oracle.

        Parameters:
            last_response_json (str): The raw JSON string returned by Oracle.
            command_output (dict): A dictionary of command outputs,
                                   where key = "1", "2", etc. and value = (stdout, stderr)

        Returns:
            str: The next prompt to send to Oracle.
        """
        try:
            summary = response.get("summary", "")
            actions = response.get("actions", {})

            # Flatten the command output into a readable format
            shell_output_lines = []
            for key, (stdout, stderr) in command_output.items():
                shell_output_lines.append(f"[Command {key}: {actions.get(key, '<unknown command>')}]")
                if stdout:
                    shell_output_lines.append(f"Output:\n{stdout}")
                if stderr:
                    shell_output_lines.append(f"Error:\n{stderr}")
                shell_output_lines.append("-" * 40)

            shell_output_str = "\n".join(shell_output_lines)

            # Build the prompt
            next_prompt = (
                f"Summary of previous analysis:\n{summary}\n\n"
                f"Shell Command Results:\n{shell_output_str}\n\n"
                f"Instructions: Based on the output above, what Linux command(s) should I run next?\n"
                f"Return ONLY executable Linux shell commands in the `actions` block. Do not explain them. "
                f"Format response in this JSON schema:\n"
                f'{{\n  "summary": "Your updated analysis",\n  "actions": {{"1": "..."}}\n  "exit_code": 1\n}}'
            )

            return next_prompt

        except Exception as e:
            return f"[ERROR] Failed to build next prompt: {e}"

    def get_dialogue_history(self, qid):
        #  Implement this to fetch relevant history from thread files
        #  You'll need to read the JSONL files and format the history
        #  as a list of {"role": "...", "content": "..."} dictionaries.
        def get_dialogue_history(self, qid):
            history = []

            dialogue_path = self.get_dialogue_path(self.get_current_mission_id())
            thread_file = os.path.join(dialogue_path, f"thread_{qid}.jsonl")

            if os.path.exists(thread_file):
                with open(thread_file, 'r') as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())  # Load each line as JSON
                            role = entry.get("role")
                            content = entry.get("content")
                            if role and content:  # Only append if both exist
                                history.append({"role": role, "content": content})
                            else:
                                self.log(f"[CAPITAL][WARN] Incomplete entry in thread file: {line.strip()}")
                        except json.JSONDecodeError as e:
                            self.log(f"[CAPITAL][ERROR] JSON decode error in thread file: {e}, line: {line.strip()}")
                        except Exception as e:
                            self.log(
                                f"[CAPITAL][ERROR] Unexpected error reading thread file: {e}, line: {line.strip()}")
            else:
                self.log(f"[CAPITAL][WARN] No thread file found: {thread_file}")

            return history

    def should_continue(self, history):
        #  Implement logic to prevent flooding
        #  For example, check the length of the history,
        #  or implement a more sophisticated rate-limiting mechanism.
        #  For now, a simple length check:
        return len(history) < self.max_rounds

    #Runs linux commands
    def run_check(self, command):
        try:
            start = time.time()
            try:
                output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, timeout=5)
                duration = round(time.time() - start, 3)
                self.log(f"[CMD] {command} completed in {duration}s")
                return output.decode("utf-8").strip(), None
            except subprocess.CalledProcessError as e:
                duration = round(time.time() - start, 3)
                self.log(f"[CMD] {command} failed in {duration}s")
                return "", e.output.decode("utf-8").strip()
        except subprocess.CalledProcessError as e:
            return "", e.output.decode("utf-8").strip()
        except Exception as e:
            return "", str(e)

    def fail_safe_stop(self, query_id, tracer_session_id, reason="no reason given"):
        self.log(f"[FAILSAFE] Mission aborted for {query_id}. Reason: {reason}")


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
    #todo dispatch to linux_scout or another os scout to handle the query
    #linux_scout; Bash - native, fast; windows_scout ; PowerShell; logic + WMI; container_scout; Docker - only; recon
    #gpu_scout NVIDIA driver / usage stats; k8s_scout; Cluster & pod; telemetry; db_scout SQL - aware schema scanner
    def TODOdispatch_to_scout(self, qid, commands, tracer_session_id="unknown", packet_id=1):

        scout_uid = self.get_node_by_role("scout")["universal_id"]

        msg = {
            "type": "check",
            "query_id": qid,
            "check": commands,
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



if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()
