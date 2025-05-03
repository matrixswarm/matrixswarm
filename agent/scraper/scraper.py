import os
import time
import json
import requests
from bs4 import BeautifulSoup
import hashlib
from agent.core.boot_agent import BootAgent
from agent.core.utils.swarm_sleep import interruptible_sleep

class ScraperAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        config = tree_node.get("config", {}) if 'tree_node' in globals() else {}
        self.watch_dir = os.path.join(self.path_resolution["comm_path_resolved"], "payload")
        self.report_to = config.get("report_to", "mailman-1")
        self.output_dir = os.path.join(self.path_resolution["comm_path"], self.report_to, "payload")
        os.makedirs(self.watch_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def worker_pre(self):
        self.log("[SCRAPER] Cold metal online. Awaiting targets...")

    def worker(self):
        self.check_jobs_once()
        interruptible_sleep(self, 2)

    def worker_post(self):
        self.log("[SCRAPER] No more pages to tear. Agent shutting down.")

    def check_jobs_once(self):
        for fname in os.listdir(self.watch_dir):
            if not fname.endswith(".json"):
                continue

            try:
                fpath = os.path.join(self.watch_dir, fname)
                with open(fpath, "r") as f:
                    job = json.load(f)

                url = job.get("target_url")
                mode = job.get("mode", "summary")

                if url:
                    self.log(f"[SCRAPER] Fetching: {url}")
                    self.process_url(url, mode)

                os.remove(fpath)

            except Exception as e:
                self.log(f"[SCRAPER][ERROR] Failed to process {fname}: {e}")

    def process_url(self, url, mode):
        try:
            r = requests.get(url, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.title.string.strip() if soup.title else "No title"
            meta = soup.find("meta", attrs={"name": "description"})
            description = meta["content"].strip() if meta and "content" in meta.attrs else "No description"
            links = [a["href"] for a in soup.find_all("a", href=True)]

            payload = {
                "uuid": self.command_line_args["universal_id"],
                "timestamp": time.time(),
                "target": url,
                "title": title,
                "description": description,
                "link_count": len(links),
                "links": links[:10],
                "mode": mode
            }

            hashval = hashlib.sha256(url.encode()).hexdigest()
            outpath = os.path.join(self.output_dir, f"{hashval}_{int(time.time())}.json")
            with open(outpath, "w") as f:
                json.dump(payload, f, indent=2)

            self.log(f"[SCRAPER] Logged summary of {url} → {outpath}")

        except Exception as e:
            self.log(f"[SCRAPER][ERROR] Could not fetch {url}: {e}")

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = ScraperAgent(path_resolution, command_line_args)
    agent.boot()
