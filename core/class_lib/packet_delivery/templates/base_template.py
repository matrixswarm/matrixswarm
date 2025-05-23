class Packet:
    def __init__(self, template: Template):
        self._template = template  # Template strategy
        self._payload = {}
        self._valid = True
        self._error_code = 0
        self._error_msg = ""

    def set_data(self, data: dict):
        try:
            self._payload = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "universal_id": data.get("universal_id", "unknown"),
                "level": data.get("level", "info"),
                "msg": data.get("msg", ""),
                "cause": data.get("cause", "unspecified"),
                "origin": data.get("origin", data.get("universal_id", "unknown")),
            }
        except Exception as e:
            self._valid = False
            self._error_code = 1
            self._error_msg = str(e)

    def generate_message(self) -> str:
        if not self._valid:
            raise ValueError("Cannot generate message from an invalid packet")
        return self._template.format_message(self._payload)

    def get_error_success(self) -> int:
        return self._error_code

    def get_error_success_msg(self) -> str:
        return self._error_msg
