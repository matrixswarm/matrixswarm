#Authored by Daniel F MacDonald and ChatGPT
import os
import time
import json
from string import Template
from core.class_lib.file_system.find_files_with_glob import  FileFinderGlob
from core.class_lib.processes.duplicate_job_check import  DuplicateProcessCheck
from core.class_lib.logging.logger import Logger
class Agent:

    if __name__ == "__main__":

        raise RuntimeError("Direct execution of agents is forbidden. Only Matrix may be launched via bootloader.")

    def __init__(self, path_resolution, command_line_args):

        self.running = False

        self.path_resolution = path_resolution

        self.command_line_args = command_line_args

        self.boot_time = time.time()

        self.logger = Logger(self.path_resolution["comm_path_resolved"], "logs", "agent.log")

    def log(self, message):
        self.logger.log(message)

    def send_message(self, message):
        self.log(f"[SEND] {json.dumps(message)}")

    #sends a heartbeat to comm/{universal_id}/hello.moto of self
    def heartbeat(self):
        hello_path = os.path.join(self.path_resolution["comm_path_resolved"], "hello.moto")
        ping_file = os.path.join(hello_path, "poke.heartbeat")

        os.makedirs(hello_path, exist_ok=True)

        while self.running:
            try:
                with open(ping_file, "w") as f:
                    f.write(self.command_line_args["install_name"])
                # self.log(f"[HEARTBEAT] Touched poke.heartbeat for {self.command_line_args['install_name']}")
            except Exception as e:
                self.log(f"[HEARTBEAT][ERROR] Failed to write ping: {e}")
            time.sleep(10)

    def enforce_singleton(self):

        #LOOP FOR 20 SECS; IF AN INSTANCE MATCHES THE JOB TAG, KILL PROGRAM
        #IF A DIE FILE IS FOUND IN THE INCOMING FOLDER, KILL PROGRAM
        while self.running:

            #is there any duplicate processes that have duplicate cli --job leave if this process is younger
            job_label = DuplicateProcessCheck.get_self_job_label()

            if DuplicateProcessCheck.check_all_duplicate_risks(job_label=job_label, check_path=False):
                self.running = False
                print(f"[INFO]core.agent.py: enforce_singleton: {self.command_line_args["universal_id"]} : shutting down found job having a later timestamp \"--job {job_label}\"")
            else:
                print(f"[INFO]core.agent.py: enforce_singleton: {self.command_line_args["universal_id"]} : safe to proceed no duplicate processes with label  \"--job {job_label}\"")

            #incoming:   die
            # example: change {root}/comm/{universal_id}/incoming = {root}/comm/worker-1/incoming
            #     look for die file in incoming only be 1 at anytime, and matrix command_thread will add/remove, spawn thread will
            #     check
            try:
                path = Template(self.path_resolution["incoming_path_template"])
            except KeyError:
                self.log("[ENFORCE] Missing incoming_path_template. Using fallback.")
                path = Template(os.path.join("comm", "$universal_id", "incoming"))

            path = path.substitute(universal_id=self.command_line_args["universal_id"])

            count, file_list = FileFinderGlob.find_files_with_glob(path,pattern="die")
            if count>0:
                self.running=False
                print(f"[INFO]core.agent.py: enforce_singleton: {self.command_line_args["universal_id"]} die cookie ingested, going down easy...")

            #within 20secs if another instance detected, and this is the younger of the die


            time.sleep(7)


    def mailman_manager(self):

        print('hi')

    def monitor_threads(self):
        while self.running:
            if not self.worker_thread.is_alive():
                self.log("[WATCHDOG] worker() thread has crashed. Shutting down agent.")
                self.running = False
                os._exit(1)  # 🔥 Force kill (or use sys.exit if you want softer)
            time.sleep(3)


