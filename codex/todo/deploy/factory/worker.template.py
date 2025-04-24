from core import BaseAgent

class {{CLASS_NAME}}(BaseAgent):
    def __init__(self):
        super().__init__(uuid="{{UUID}}")
        self.delegated = {{DELEGATED_LIST}}

    def run(self):
        while True:
            self.heartbeat()
            self.report("{{CLASS_NAME}} running in worker loop.")
            self.sleep(2)
