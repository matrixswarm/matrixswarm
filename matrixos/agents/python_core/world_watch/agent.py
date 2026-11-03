"""Shared authenticated capture commands for focused watch agents."""
from life_signal.life_signal import Agent as LifeSignalAgent


class WatchAgent(LifeSignalAgent):
    def cmd_get_capture(self, content, packet, identity=None):
        if not self._authorized(content, identity) or not self._valid_callback(content):
            return
        try:
            self._reply(content, dict(self.engine.capture_chunk(content.get('capture_id'),
                content.get('offset', 0)), ok=True))
        except ValueError as exc:
            self._reply(content, {'ok': False, 'error': str(exc)})

    def cmd_clear_history(self, content, packet, identity=None):
        if not self._authorized(content, identity) or not self._valid_callback(content):
            return
        try:
            self.engine.clear_history(content.get('source_id'))
            self._reply(content, dict(self.engine.panel_snapshot(), ok=True))
        except ValueError as exc:
            self._reply(content, {'ok': False, 'error': str(exc)})
