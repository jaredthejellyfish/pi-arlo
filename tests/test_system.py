from arlo_manager.settings import Settings
from arlo_manager.system import CommandResult, SystemReader


class SlowWpsSystem(SystemReader):
    def __init__(self):
        super().__init__(Settings())
        self.commands = []

    def run(self, args, timeout=8):
        self.commands.append((args, timeout))
        command = args[-1]
        if command == "wps_pbc":
            return CommandResult(False, "timed out", timed_out=True)
        if command == "wps_get_status":
            return CommandResult(True, "PBC Status: Active\nLast WPS result: Success")
        return CommandResult(True, "OK")


def test_wps_timeout_is_accepted_when_hostapd_reports_active():
    system = SlowWpsSystem()

    result = system.start_pairing()

    assert result.ok is True
    assert any(command[-1] == "wps_get_status" for command, _ in system.commands)
