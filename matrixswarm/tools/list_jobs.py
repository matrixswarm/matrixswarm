import psutil
import time
from datetime import datetime
import os

def list_jobs():
    jobs = []
    now = time.time()
    for proc in psutil.process_iter(['pid', 'cmdline', 'create_time']):
        try:
            cmdline = proc.info['cmdline']
            if not cmdline or "--job" not in cmdline:
                continue

            job_idx = cmdline.index("--job")
            job_label = cmdline[job_idx + 1] if job_idx + 1 < len(cmdline) else "???"

            pid = proc.info['pid']
            created = proc.info['create_time']
            uptime = int(now - created)

            jobs.append({
                "pid": pid,
                "job": job_label,
                "cmd": cmdline[1],
                "uptime": uptime
            })
        except Exception:
            continue
    return jobs

def interactive_kill():
    while True:
        jobs = list_jobs()
        print("\n🧠 Active Swarm Jobs\n")
        for i, job in enumerate(jobs, 1):
            print(f"{i}. {job['job']:<20} 🕒 {job['uptime']}s   {job['cmd']}")

        choice = input("\nEnter a job number to kill, or `exit`: ").strip()
        if choice.lower() == "exit":
            break

        try:
            index = int(choice) - 1
            target = jobs[index]
            os.kill(target['pid'], 9)
            print(f"[KILL] Job {target['job']} (PID {target['pid']}) terminated.")
        except Exception as e:
            print(f"[ERROR] Could not kill job: {e}")

if __name__ == "__main__":
    interactive_kill()