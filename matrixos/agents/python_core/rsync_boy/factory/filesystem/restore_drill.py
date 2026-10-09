"""Scheduled filesystem recovery rehearsal; never a live restore."""
import time

from rsync_boy.factory.filesystem.storage_runner import storage_operation
from rsync_boy.factory.ssh_transport import SSHTransport, parse_ssh_profile


class RestoreDrillJob:
    def __init__(self, log, shared):
        self.log = log
        self.shared = shared
        self.context = shared.get("context", {})

    def run(self):
        cfg = self.context["config"]
        backup = self.context["backup_job"]
        source = backup["config"]
        request = {"action": "drill", "job_id": self.context["job_id"],
                   "backup_job_id": backup["id"], "snapshot_root": source["remote_path"],
                   "backup_definition_hash": self.context["backup_definition_hash"],
                   "drill_definition_hash": self.context["definition_hash"],
                   "snapshot_prefix": source["snapshot_prefix"], "source_path": source["source_path"],
                   "restore_root": cfg["restore_root"], "snapshot": cfg["snapshot"],
                   "limits": {key: cfg[key] for key in
                              ("timeout_sec", "max_entries", "max_bytes", "min_free_bytes")}}
        try:
            if source["source_via_ssh"]:
                report = storage_operation(request)
            else:
                with SSHTransport(parse_ssh_profile(cfg)) as transport:
                    report = storage_operation(request, transport)
            self.context["restore_report"].update(report)
            if report.get("result") != "ok":
                raise RuntimeError("Restore drill failed: " + str(report.get("error_code", "cleanup_required")))
            self.shared["result"] = "ok"
            self.log(f"[RESTORE_DRILL][{self.context['job_id']}] VERIFIED "
                     f"snapshot={report['snapshot']} files={report['verified_files']} "
                     f"bytes={report['verified_bytes']}; application recovery unverified")
        except Exception:
            self.shared["result"] = "error"
            self.log(f"[RESTORE_DRILL][{self.context['job_id']}] FAILED; "
                     "last successful drill is unchanged", level="ERROR")
            raise
        finally:
            self.shared["finished_at"] = time.time()
