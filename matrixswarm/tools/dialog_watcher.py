#!/usr/bin/env python3
import os
import curses
import time
import textwrap
import json
from pathlib import Path

scroll_offset = 0

# === CONFIG ===
AGENTS = {
    "Capital GPT": "sgt-in-arms",
    "Oracle": "golden-child-4",
    "Linux Scout": "arch-angel-destiny"
}
COMM_ROOT = "/matrix/ai/latest/comm"
LOG_FILE = "logs/agent.log"
from glob import glob
SESSIONS_DIR = Path("/matrix/ai/latest/boot_sessions")


REFRESH_RATE = 0.5

def tail(filepath, n=15):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.readlines()[-n:]
    except:
        return ["<No log data>"]


def get_latest_session_path():
    sessions = sorted(SESSIONS_DIR.glob("*"), key=lambda p: os.path.getmtime(str(p)), reverse=True)
    return sessions[0] if sessions else None

def gather_agent_logs(width):
    lines = []
    key_terms = ["[REFLEX]", "[DISPATCH]", "[REPLY]"]

    for label, aid in AGENTS.items():
        agent_log_path = Path(COMM_ROOT) / aid / LOG_FILE
        if not agent_log_path.exists():
            lines.append(f"[{label}] → [NO LOG FOUND]")
            continue

        try:
            with open(agent_log_path, encoding="utf-8") as f:
                log_lines = f.readlines()[-30:]
        except Exception as e:
            lines.append(f"[{label}] → [ERROR reading log: {e}]")
            continue

        filtered = [l.strip() for l in log_lines if any(k in l for k in key_terms)]
        lines.append(f"[{label}] — Latest Reflex Events:")
        for entry in filtered[-6:]:
            wrapped = textwrap.wrap(entry, width=width - 4)
            lines.extend(wrapped)
        lines.append("")  # gap
    return lines[-100:]

def gather_session_messages(width):
    lines = []
    session_path = get_latest_session_path()

    if not session_path or not session_path.exists():
        return ["[SESSION] No tracer sessions found"]

    try:
        files = sorted(session_path.glob("*.msg")) + sorted(session_path.glob("*.prompt")) + sorted(session_path.glob("*.response"))
        files = sorted(files, key=lambda f: f.name)
    except Exception as e:
        return [f"[SESSION-READ-FAIL]: {e}"]

    if not files:
        return ["[SESSION] No .msg/.prompt/.response files found"]

    for fpath in files[-50:]:
        try:
            with open(fpath, encoding="utf-8") as f:
                entry = json.load(f)

            raw_content = entry.get("content", {})
            who = entry.get("source") or raw_content.get("origin") or "???"
            typ = entry.get("type", "???")
            flat = (
                entry.get("prompt") or
                entry.get("flattened") or
                raw_content.get("summary") or
                raw_content.get("msg") or
                json.dumps(raw_content)
            )

            session = entry.get("tracer_session_id", "⧗ no-session")
            packet = entry.get("packet_id", "❓")

            lines.append(f"[{session} ▸ {packet}] {who} → {typ} ({fpath.name}):")
            wrapped = textwrap.wrap(flat, width=width - 4)
            lines.extend(wrapped)
            lines.append("")

        except Exception as e:
            lines.append(f"[SESSION-PARSE-ERROR @ {fpath.name}]: {e}")
            lines.append("")

    return lines if lines else ["[SESSION] Trace parsed clean, but no messages extracted."]


def render_panel(win, title, lines, width, offset=0):
    win.erase()
    win.border()
    win.addstr(0, 2, f" {title} ")

    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)  # Default
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)  # For "Oracle"
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK) # For "Capital GPT"
        curses.init_pair(4, curses.COLOR_BLUE, curses.COLOR_BLACK)   # For "Linux Scout"
        curses.init_pair(5, curses.COLOR_RED, curses.COLOR_BLACK)    # For Errors

    height = win.getmaxyx()[0]
    visible_lines = lines[offset: offset + height - 2]
    for i, line in enumerate(visible_lines):
        try:
            clean = line.replace('\x00', '').replace('\x1b', '')
            if "Oracle" in title:
              win.addstr(i + 1, 1, clean[: width - 2], curses.color_pair(2))
            elif "Capital GPT" in title:
              win.addstr(i + 1, 1, clean[: width - 2], curses.color_pair(3))
            elif "Linux Scout" in title:
              win.addstr(i + 1, 1, clean[: width - 2], curses.color_pair(4))
            elif "[ERROR]" in line:
              win.addstr(i + 1, 1, clean[: width - 2], curses.color_pair(5))
            else:
              win.addstr(i + 1, 1, clean[: width - 2], curses.color_pair(1))
        except curses.error:
            continue
    win.refresh()



def main(stdscr):
    curses.curs_set(0)
    # Get current terminal dimensions
    height, width = stdscr.getmaxyx()

    if height < 24 or width < 80:
        stdscr.addstr(0, 0, "🛑 Terminal too small. Resize it to at least 80x24.")
        stdscr.refresh()
        time.sleep(3)
        return

    # Calculate dynamic layout
    agent_height = max(int(height * 0.30), 5)  # 30% of screen
    codex_height = max(int(height * 0.30), 6)  # 30% of screen
    trace_height = height - agent_height - codex_height - 2  # Remaining height

    panel_width = width // len(AGENTS)
    panels = []
    agent_logs = []

    # Create agent panels at the top
    for i, (label, aid) in enumerate(AGENTS.items()):
        win = curses.newwin(agent_height, panel_width, 0, i * panel_width)
        panels.append((win, label))
        agent_logs.append(Path(COMM_ROOT) / aid / LOG_FILE)

    # Create Codex and Reflex panels stacked below
    codex_win = curses.newwin(codex_height, width, agent_height, 0)
    #chat_win = curses.newwin(chat_height, width, agent_height + codex_height + 1, 0)
    session_win = curses.newwin(trace_height, width, agent_height + codex_height + 1, 0)

    global scroll_offset
    stdscr.nodelay(True)
    while True:
        key = stdscr.getch()
        if key == curses.KEY_UP:
            scroll_offset = max(scroll_offset - 1, 0)
        elif key == curses.KEY_DOWN:
            scroll_offset += 1  # clamped below when rendering


        for i, (win, label) in enumerate(panels):
            render_panel(win, label, tail(agent_logs[i], 14), panel_width)

        #reflex_lines = gather_agent_logs(width)
        #render_panel(chat_win, "🗣️ Reflex Signal Log", reflex_lines, width)

        # Refresh the Codex panel (if you want it live — placeholder for now)
        render_panel(codex_win, "📖 Codex (Not Yet Implemented)", ["Coming soon..."], width)

        # Refresh the session window every tick
        session_lines = gather_session_messages(width)
        render_panel(session_win, "🧠 Active Trace Session", session_lines, width, offset=scroll_offset)


        time.sleep(REFRESH_RATE)

if __name__ == "__main__":
    curses.wrapper(main)
