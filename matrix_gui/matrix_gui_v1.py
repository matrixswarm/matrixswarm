# Matrix GUI v1 Launch Core — Upgrade Module with HTTPS Dispatch

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
import time
import requests
from agent.core.live_tree import LiveTree


class MatrixV1(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🧠 Matrix V1: Hive Control Center")
        self.geometry("1400x800")
        self.configure(bg="#1e1e1e")

        self.tree_data = {}
        self.matrix_url = "https://147.135.68.135:65431/matrix"  # replace with your Matrix endpoint
        self.cert_path = ("../certs/client.crt", "../certs/client.key")
        self.ca_cert = "../certs/server.crt"  # assuming server.crt is your CA for self-signed Matrix


        self.create_widgets()

    def create_widgets(self):
        left = tk.Frame(self, bg="#252526", bd=2)
        left.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(left, text="Mission Tags", fg="white", bg="#252526").pack(pady=5)

        self.mission_tag = tk.Entry(left, width=25)
        self.mission_tag.pack(pady=5)

        self.agent_name = tk.Entry(left, width=25)
        self.agent_name.insert(0, "agent_name")
        self.agent_name.pack(pady=5)

        self.universal_id = tk.Entry(left, width=25)
        self.universal_id.insert(0, "universal_id")
        self.universal_id.pack(pady=5)

        self.delegated = tk.Entry(left, width=25)
        self.delegated.insert(0, "comma,separated,delegated")
        self.delegated.pack(pady=5)

        tk.Button(left, text="SEND SPAWN TO MATRIX", command=self.send_spawn).pack(pady=5)
        tk.Button(left, text="INJECT TO TREE", command = self.send_injection).pack(pady=5)
        tk.Button(left, text="SHUTDOWN AGENT", command=self.shutdown_agent).pack(pady=5)
        tk.Button(left, text="DELETE SUBTREE", command=self.delete_subtree).pack(pady=5)
        tk.Button(left, text="CALL REAPER", command=self.call_reaper).pack(pady=5)
        tk.Button(left, text="View Tagged Agents", command=self.view_tags).pack(pady=5)

        center = tk.Frame(self, bg="#1e1e1e")
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(center, text="Hive Tree", fg="white", bg="#1e1e1e").pack()
        self.tree_display = tk.Text(center, bg="#111", fg="#33ff33", font=("Courier", 10))
        self.tree_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        tk.Button(center, text="Reload Tree", command=self.reload_tree).pack(pady=3)

        right = tk.Frame(self, bg="#252526")
        right.pack(side=tk.RIGHT, fill=tk.BOTH)

        tk.Label(right, text="Live Agent Logs", fg="white", bg="#252526").pack(pady=5)
        self.agent_log_entry = tk.Entry(right, width=30)
        self.agent_log_entry.insert(0, "logger-alpha")
        self.agent_log_entry.pack(pady=5)
        tk.Button(right, text="View Logs", command=self.view_logs).pack(pady=3)

        self.log_box = tk.Text(right, bg="#000", fg="#f0f0f0", height=35)
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def send_to_matrix(self, command_type, content):
        ts = str(int(time.time() * 1000))
        payload = {
            "type": command_type,
            "timestamp": time.time(),
            "content": content
        }
        try:
            response = requests.post(
                self.matrix_url,
                json=payload,
                cert=self.cert_path,
                #verify=self.ca_cert,
                verify=False,
                timeout=5
            )
            if response.status_code == 200:
                messagebox.showinfo("Command Sent", f"{command_type.upper()} accepted by Matrix.")
            else:
                messagebox.showerror("Matrix Error", f"{response.status_code}: {response.text}")
        except Exception as e:
            messagebox.showerror("Connection Failed", str(e))

    def send_spawn(self):
        agent = self.agent_name.get()
        perm = self.universal_id.get()
        delegated = [x.strip() for x in self.delegated.get().split(",") if x.strip()]
        directive = {
            "universal_id": perm,
            "agent_name": agent,
            "delegated": delegated
        }
        self.send_to_matrix("spawn", directive)

    def inject_tree(self):
        perm = self.universal_id.get()
        delegated = [x.strip() for x in self.delegated.get().split(",") if x.strip()]
        tree = LiveTree()
        tree.inject(perm, delegated)
        messagebox.showinfo("Injected", f"{perm} injected with delegates: {delegated}")

    def tag_agent(self):
        tag = self.mission_tag.get().strip()
        if tag:
            with open("/deploy/missions.json", "a") as f:
                f.write(tag + "\n")
            messagebox.showinfo("Tagged", f"Mission tag '{tag}' saved.")

    def view_tags(self):
        if os.path.exists("/deploy/missions.json"):
            with open("/deploy/missions.json") as f:
                tags = f.read()
            messagebox.showinfo("Tags", tags)
        else:
            messagebox.showwarning("Tags", "No mission tags found.")

    def reload_tree(self):
        tree = LiveTree()
        output = []

        def recurse(node, indent=""):
            output.append(f"{indent}- {node}")
            for child in tree.get_delegates(node):
                recurse(child, indent + "  ")

        recurse("matrix")
        self.tree_display.delete("1.0", tk.END)
        self.tree_display.insert(tk.END, "\n".join(output))

    def shutdown_agent(self):
        perm = self.universal_id.get()
        path = f"/comm/reaper-root/payload/kill_{perm}.json"
        with open(path, "w") as f:
            json.dump({"universal_id": perm}, f, indent=2)
        messagebox.showinfo("Shutdown", f"Kill order sent for {perm}")

    def delete_subtree(self):
        perm = self.universal_id.get()
        tree = LiveTree()
        tree.delete_subtree(perm)
        messagebox.showinfo("Subtree Deleted", f"Deleted all nodes under {perm}")

    def call_reaper(self):
        os.system("python3 /sites/orbit/python/agent/reaper/reaper.py &")
        messagebox.showinfo("Reaper", "Reaper called")

    def view_logs(self):
        universal_id = self.agent_log_entry.get().strip()
        log_path = f"/sites/orbit/python/pod/{universal_id}/log.txt"
        if os.path.exists(log_path):
            with open(log_path) as f:
                logs = f.read()
            self.log_box.delete("1.0", tk.END)
            self.log_box.insert(tk.END, logs)
        else:
            messagebox.showerror("Log Missing", f"No log.txt for {universal_id}")

    def send_injection(self):
        perm = self.universal_id.get()
        delegated = [x.strip() for x in self.delegated.get().split(",") if x.strip()]
        directive = {
            "universal_id": perm,
            "delegated": delegated
        }
        self.send_to_matrix("inject", directive)

if __name__ == "__main__":
    app = MatrixV1()
    app.mainloop()
