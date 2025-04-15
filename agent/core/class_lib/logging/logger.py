import time
import os
class Logger:
    def __init__(self, comm_path_resolved, logs="logs", file_name="agent.log"):

        self.log_file = os.path.join(comm_path_resolved, logs, file_name)
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)


    def log(self, message, level="INFO", print_to_console=True):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} [{level}] {message}"

        if print_to_console:
            print(log_entry)

        with open(self.log_file, "a") as f:
            f.write(log_entry + "\n")