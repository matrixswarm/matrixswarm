import tkinter as tk
from tkinter import ttk
from tkinter import BooleanVar, Checkbutton
from codex.swarm_codex import get_codex
import requests

class CodexPanel(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg="#1e1e1e")
        self.pack(fill=tk.BOTH, expand=True)

        title = tk.Label(self, text="Codex", font=("Courier", 16), bg="#1e1e1e", fg="white")
        title.pack(pady=10)

        self.no_verify = BooleanVar(value=False)
        Checkbutton(self, text="--no-verify (Disable SSL Cert Check)", variable=self.no_verify, bg="#1e1e1e", fg="white", selectcolor="#1e1e1e").pack(pady=5)

        tk.Button(self, text="TEST CONNECTION", command=self.test_connection, bg="#252526", fg="white").pack(pady=5)

        columns = ("universal_id", "role", "banner", "spawned", "version", "status")
        tree = ttk.Treeview(self, columns=columns, show="headings")
        tree.pack(fill=tk.BOTH, expand=True)

        for col in columns:
            tree.heading(col, text=col.capitalize())
            tree.column(col, anchor="center", width=100)

        for agent in get_codex():
            status_color = "🟢" if agent["status"].lower() == "active" else "🔴"
            tree.insert("", tk.END, values=(
                agent["universal_id"],
                agent["role"],
                agent["banner"],
                agent["spawned"],
                agent["version"],
                f"{status_color} {agent['status']}"
            ))

    def test_connection(self):
        url = "https://147.135.68.135:65431/matrix"
        payload = {"type": "list_tree", "timestamp": 0, "content": {}}
        cert = ("certs/client.crt", "certs/client.key")
        verify = False if self.no_verify.get() else "certs/rootCA.pem"

        try:
            response = requests.post(url, json=payload, cert=cert, verify=verify, timeout=5)
            if response.status_code == 200:
                tk.messagebox.showinfo("Success", "Connection verified with Matrix.")
            else:
                tk.messagebox.showerror("Error", f"Status {response.status_code}: {response.text}")
        except Exception as e:
            tk.messagebox.showerror("Connection Failed", str(e))

if __name__ == "__main__":
    root = tk.Tk()
    root.title("Swarm Codex")
    root.geometry("900x600")
    CodexPanel(root)
    root.mainloop()
