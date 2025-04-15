import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
import time
from agent.core.live_tree import LiveTree

class MatrixGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🧠 Matrix V1: Hive Control Center")
        self.geometry("1400x800")
        self.configure(bg="#1e1e1e")

        self.tree_data = {}

        self.create_widgets()
        self.start_tree_autorefresh(interval=10)

    def create_widgets(self):
        left = tk.Frame(self, bg="#252526", bd=2)
        left.pack(side=tk.LEFT, fill=tk.Y)

        tk.Label(left, text="Mission Tags", fg="white", bg="#252526").pack(pady=5)

        self.mission_tag = tk.Entry(left, width=25)
        self.mission_tag.pack(pady=5)

        self.agent_name = tk.Entry(left, width=25)
        self.agent_name.insert(0, "agent_name")
        self.agent_name.pack(pady=5)

        self.perm_id = tk.Entry(left, width=25)
        self.perm_id.insert(0, "permanent_id")
        self.perm_id.pack(pady=5)

        self.target_permanent_id = tk.Entry(left, width=25)
        self.target_permanent_id.insert(0, "target_permanent_id")
        self.target_permanent_id.pack(pady=5)

        self.delegated = tk.Entry(left, width=25)
        self.delegated.insert(0, "comma,separated,delegated")
        self.delegated.pack(pady=5)

        tk.Label(left, text="Select Agent", fg="white", bg="#252526").pack(pady=5)
        agents = self.load_remote_agents()
        print("[DEBUG] Loaded remote agents:", agents)

        self.agent_select = ttk.Combobox(left, values=["---"] + agents, state="readonly")
        self.agent_select.set("---")
        self.agent_select.pack(pady=5)

        tk.Label(left, text="Select Team", fg="white", bg="#252526").pack(pady=5)

        # Load teams
        teams = self.load_team_list()
        print("[DEBUG] Loaded teams:", teams)

        # Insert placeholder and setup dropdown
        self.team_select = ttk.Combobox(left, values=["---"] + teams, state="readonly")
        self.team_select.pack(pady=5)
        self.team_select.set("---")

        # 🔻 Drop this directly after
        def on_team_change(event):
            print("[DEBUG] Dropdown changed:", repr(self.team_select.get()))

        self.team_select.bind("<<ComboboxSelected>>", on_team_change)


        tk.Button(left, text="DEPLOY SELECTED TEAM", command=self.deploy_selected_team).pack(pady=5)

        tk.Button(left, text="SEND SPAWN TO MATRIX", command=self.send_spawn).pack(pady=5)
        tk.Button(left, text="INJECT TO TREE", command=self.send_injection).pack(pady=5)
        tk.Button(left, text="SHUTDOWN AGENT", command=self.shutdown_agent).pack(pady=5)
        tk.Button(left, text="DELETE SUBTREE", command=self.delete_subtree).pack(pady=5)
        tk.Button(left, text="CALL REAPER", command=self.call_reaper).pack(pady=5)
        tk.Button(left, text="View Tagged Agents", command=self.view_tags).pack(pady=5)
        tk.Button(left, text="REQUEST TREE FROM MATRIX", command=self.request_tree_from_matrix).pack(pady=5)

        center = tk.Frame(self, bg="#1e1e1e")
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(center, text="Hive Tree", fg="white", bg="#1e1e1e").pack()
        self.tree_display = tk.Text(center, bg="#111", fg="#33ff33", font=("Courier", 10))
        self.tree_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        tk.Button(center, text="Reload Tree", command=self.load_tree).pack(pady=3)

        self.agent_select = ttk.Combobox(
            left,
            values=["---"] + self.load_remote_agents(),  # ✅ Should be this
            state="readonly"
        )

        right = tk.Frame(self, bg="#252526")
        right.pack(side=tk.RIGHT, fill=tk.BOTH)


        tk.Label(right, text="Live Agent Logs", fg="white", bg="#252526").pack(pady=5)
        self.agent_log_entry = tk.Entry(right, width=30)
        self.agent_log_entry.insert(0, "logger-alpha")
        self.agent_log_entry.pack(pady=5)
        tk.Button(right, text="View Logs", command=self.view_logs).pack(pady=3)

        self.log_box = tk.Text(right, bg="#000", fg="#f0f0f0", height=35)
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def deploy_selected_team(self):

        selected = self.team_select.get().strip()
        print("[DEBUG] Raw dropdown value:", repr(selected))

        if not selected or selected == "---":
            messagebox.showwarning("No Team Selected", "Please select a team to deploy.")
            return

        team_file = f"deploy/teams/{selected}.json"

        if not os.path.exists(team_file):
            messagebox.showerror("Missing File", f"Team file not found: {team_file}")
            return

        print("[DEBUG] Selected team:", selected)

        try:
            with open(team_file, "r") as f:
                team_data = json.load(f)

            payload = {
                "type": "inject_team",
                "timestamp": time.time(),
                "content": {
                    "target_perm_id": "matrix",  # or let user specify in the GUI later
                    "subtree": team_data
                }
            }

            import requests
            response = requests.post(
                url="https://147.135.68.135:65431/matrix",
                json=payload,
                cert=("certs/client.crt", "certs/client.key"),
                verify="certs/server.crt",
                timeout=5
            )

            if response.status_code == 200:
                messagebox.showinfo("Deployed", f"Team '{selected}' deployed successfully.")
            else:
                messagebox.showerror("Matrix Error", f"{response.status_code}: {response.text}")

        except Exception as e:
            messagebox.showerror("Deploy Error", str(e))

    def load_team_list(self):
        team_dir = "deploy/teams"
        if not os.path.exists(team_dir):
            return []
        return [f.replace(".json", "") for f in os.listdir(team_dir) if f.endswith(".json")]

    def refresh_agents(self):
        agents = self.load_active_agents()
        self.agent_select["values"] = ["---"] + agents
        self.agent_select.set("---")

    def load_active_agents(self):
        comm_path = "/sites/orbit/python/comm"
        agents = []

        if not os.path.exists(comm_path):
            return agents

        for name in os.listdir(comm_path):
            path = os.path.join(comm_path, name)
            if os.path.isdir(path):
                agents.append(name)

        return sorted(agents)

    def load_remote_agents(self):
        try:
            import requests
            response = requests.get(
                url="https://147.135.68.135:65431/agents",
                cert=("certs/client.crt", "certs/client.key"),
                verify="certs/server.crt",
                timeout=5
            )
            data = response.json()
            print(f"[DEBUG] Fetching remote agent list from Matrix...{data}")
            if data["status"] == "ok":
                return sorted(data["agents"])
        except Exception as e:
            print("[ERROR] Failed to fetch agent list:", e)
        return []

    def request_tree_from_matrix(self):
        try:
            import requests
            payload = {
                "type": "list_tree",
                "timestamp": time.time(),
                "content": {}
            }
            response = requests.post(
                url="https://147.135.68.135:65431/matrix",
                json=payload,
                cert=("certs/client.crt", "certs/client.key"),
                verify="certs/server.crt",
                timeout=5
            )
            if response.status_code == 200:
                tree = response.json().get("tree", {})
                print("[DEBUG] Raw tree payload:\n", json.dumps(tree, indent=2))  # <=== this line
                # Usage in request_tree_from_matrix response
                output = self.render_tree(tree.get("matrix", {}))
                self.tree_display.delete("1.0", tk.END)
                self.tree_display.insert(tk.END, f"[MATRIX TREE @ {time.strftime('%H:%M:%S')}]")
                self.tree_display.insert(tk.END, "\n".join(output))
            else:
                messagebox.showerror("Matrix Error", f"{response.status_code}: {response.text}")
        except Exception as e:
            messagebox.showerror("Request Failed", str(e))

    def render_tree(self, node, indent=""):
        output = []
        if not isinstance(node, dict):
            output.append((f"{indent}- [INVALID NODE STRUCTURE: {node}]", "none"))
            return output

        name = node.get("permanent_id") or node.get("name") or "unknown"
        label = name
        if node.get("confirmed"):
            label += " ✓"
        children = node.get("children", [])
        if isinstance(children, list):
            child_count = len(children)
            if child_count:
                label += f" ({child_count})"
        else:
            label += " [INVALID CHILD FORMAT]"
            children = []

        line = f"{indent}- {label}"
        output.append((line, name))  # capture both line and perm_id
        for child in children:
            output.extend(self.render_tree(child, indent + "  "))
        return output

    def start_tree_autorefresh(self, interval=10):
        def refresh():
            self.load_tree_from_matrix()
            self.after(interval * 1000, refresh)

        refresh()

    def load_tree(self):
        tree = LiveTree()
        output = []

        def recurse(node, indent=""):
            line = f"{indent}- {node}"
            if node.get("confirmed"):
                line += " ✓"
            output.append(line)
            for child in tree.get_delegates(node):
                recurse(child, indent + "  ")

        root_node = tree.nodes.get("matrix")  # ← Replace "matrix" with actual root perm_id if dynamic
        if root_node:
            recurse(root_node)
        else:
            output.append(("[ERROR] Root node 'matrix' not found.", "none"))

        self.tree_display.delete("1.0", tk.END)
        self.tree_display.insert(tk.END, f"[TREE SYNC @ {time.strftime('%H:%M:%S')}]\n\n")
        self.tree_display.insert(tk.END, "\n".join(output))


    def send_spawn(self):
        agent = self.agent_name.get()
        perm = self.perm_id.get()
        delegated = [x.strip() for x in self.delegated.get().split(",") if x.strip()]
        directive = {
            "permanent_id": perm,
            "agent_name": agent,
            "delegated": delegated
        }
        self.send_to_matrix("spawn", directive)

    def send_injection(self):

        #id of target parent
        target_perm_id =self.target_permanent_id.get().strip()

        #this is the unique id of the agent
        perm = self.perm_id.get().strip()

        #this is agent that will be spawned
        agent = self.agent_name.get().strip()

        delegated = [x.strip() for x in self.delegated.get().split(",") if x.strip()]

        directive = {
            "target_perm_id": target_perm_id,
            "perm_id": perm,
            "agent_name": agent,
            "delegated": delegated
        }

        print("[INJECT GUI PAYLOAD]", directive)

        self.send_to_matrix("inject", directive)

    def send_to_matrix(self, command_type, content):
        try:
            import requests
            payload = {
                "type": command_type,
                "timestamp": time.time(),
                "content": content
            }
            response = requests.post(
                url="https://147.135.68.135:65431/matrix",
                json=payload,
                cert=("certs/client.crt", "certs/client.key"),
                verify="certs/server.crt",
                timeout=5
            )
            if response.status_code == 200:
                messagebox.showinfo("Command Sent", f"{command_type.upper()} accepted by Matrix.")
            else:
                messagebox.showerror("Matrix Error", f"{response.status_code}: {response.text}")
        except Exception as e:
            messagebox.showerror("Connection Failed", str(e))

    def shutdown_agent(self):
        perm = self.perm_id.get()
        path = f"/comm/reaper-root/payload/kill_{perm}.json"
        with open(path, "w") as f:
            json.dump({"perm_id": perm}, f, indent=2)
        messagebox.showinfo("Shutdown", f"Kill order sent for {perm}")

    def delete_subtree(self):
        perm = self.perm_id.get()
        from agent.core.live_tree import LiveTree
        tree = LiveTree()
        tree.delete_subtree(perm)
        messagebox.showinfo("Subtree Deleted", f"Deleted all nodes under {perm}")

    def call_reaper(self):
        os.system("python3 /sites/orbit/python/agent/reaper/reaper.py &")
        messagebox.showinfo("Reaper", "Reaper called")

    # Usage in request_tree_from_matrix response
    def load_tree_from_matrix(self):
        try:
            import requests
            payload = {
                "type": "list_tree",
                "timestamp": time.time(),
                "content": {}
            }
            response = requests.post(
                url="https://147.135.68.135:65431/matrix",
                json=payload,
                cert=("certs/client.crt", "certs/client.key"),
                verify="certs/server.crt",
                timeout=5
            )

            if response.status_code == 200:
                tree = response.json().get("tree", {})
                lines = []

                # The root node is the entire tree object
                root_node = tree if isinstance(tree, dict) and "permanent_id" in tree else None
                if root_node:
                    lines = self.render_tree(root_node)
                else:
                    lines = [("[ERROR] Invalid or empty tree structure returned.", "none")]

                self.tree_display.delete("1.0", tk.END)
                self.tree_display.insert(tk.END, f"[MATRIX TREE @ {time.strftime('%H:%M:%S')}]\n\n")

                for idx, (line, perm_id) in enumerate(lines):
                    tag = f"perm_{idx}"
                    self.tree_display.insert(tk.END, line + "\n", tag)
                    if perm_id != "none":
                        # Inject it into the log input as well
                        self.agent_log_entry.delete(0, tk.END)
                        self.agent_log_entry.insert(0, perm_id)

                        self.tree_display.tag_bind(tag, "<Button-1>", self.make_click_callback(perm_id))

                        print(f"[CLICK-BIND] Clicked tag bound to perm_id: {perm_id}")
            else:
                messagebox.showerror("Matrix Error", f"{response.status_code}: {response.text}")

        except Exception as e:
            messagebox.showerror("Request Failed", str(e))

    def view_logs_for(self, perm_id):
        import requests

        payload = {
            "type": "get_log",
            "timestamp": time.time(),
            "content": {
                "perm_id": perm_id
            }
        }

        try:
            response = requests.post(
                url="https://147.135.68.135:65431/matrix",
                json=payload,
                cert=("certs/client.crt", "certs/client.key"),
                verify="certs/server.crt",
                timeout=5
            )

            if response.status_code == 200:
                data = response.json()
                logs = data.get("log", "[NO LOG DATA]")
                self.log_box.delete("1.0", tk.END)
                self.log_box.insert(tk.END, logs)
                self.log_box.see(tk.END)
                print(f"[REMOTE-LOG] Loaded logs for {perm_id}")
            else:
                self.log_box.delete("1.0", tk.END)
                self.log_box.insert(tk.END, f"[ERROR] Server responded: {response.text}")

        except Exception as e:
            self.log_box.delete("1.0", tk.END)
            self.log_box.insert(tk.END, f"[ERROR] Failed to retrieve logs: {e}")

    def view_logs(self):
        perm_id = self.agent_log_entry.get().strip()
        print(f"[LOG-GUI] Request to view logs for: {perm_id}")
        log_path = f"/sites/orbit/python/comm/{perm_id}/logs/agent.log"
        print(f"[LOG-GUI] Final path used: {log_path}")

        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    logs = f.read()
                self.log_box.delete("1.0", tk.END)
                self.log_box.insert(tk.END, logs)
                self.log_box.see(tk.END)
            except Exception as e:
                self.log_box.delete("1.0", tk.END)
                self.log_box.insert(tk.END, f"[ERROR] Could not read log for {perm_id}: {e}")
        else:
            self.log_box.delete("1.0", tk.END)
            self.log_box.insert(tk.END, f"[ERROR] No log found for {perm_id}")

    def view_tags(self):
        if os.path.exists("/deploy/missions.json"):
            with open("/deploy/missions.json") as f:
                tags = f.read()
            messagebox.showinfo("Tags", tags)
        else:
            messagebox.showwarning("Tags", "No mission tags found.")

    def make_click_callback(self, pid):
        return lambda e: self.view_logs_for(pid)

if __name__ == "__main__":
    app = MatrixGUI()
    app.mainloop()
