import tkinter as tk
from tkinter import ttk
from codex.swarm_codex import get_codex

class CodexPanel(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg="#1e1e1e")
        self.pack(fill=tk.BOTH, expand=True)

        title = tk.Label(self, text="Codex", font=("Courier", 16), bg="#1e1e1e", fg="white")
        title.pack(pady=10)

        columns = ("perm_id", "role", "banner", "spawned", "version", "status")
        tree = ttk.Treeview(self, columns=columns, show="headings")
        tree.pack(fill=tk.BOTH, expand=True)

        for col in columns:
            tree.heading(col, text=col.capitalize())
            tree.column(col, anchor="center", width=100)

        for agent in get_codex():
            status_color = "🟢" if agent["status"].lower() == "active" else "🔴"
            tree.insert("", tk.END, values=(
                agent["perm_id"],
                agent["role"],
                agent["banner"],
                agent["spawned"],
                agent["version"],
                f"{status_color} {agent['status']}"
            ))

if __name__ == "__main__":
    root = tk.Tk()
    root.title("Swarm Codex")
    root.geometry("900x600")
    CodexPanel(root)
    root.mainloop()
