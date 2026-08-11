from arlo_manager.pairing import PairingCoordinator
from arlo_manager.system import CommandResult


class PairingSystem:
    def __init__(self):
        self.started = False

    def arlo_devices(self):
        return [
            {
                "serial_number": "AAKNOWN1234",
                "hostname": "VMC4041PB-1234",
                "ip": "172.14.1.22",
            }
        ]

    def stations(self):
        if self.started:
            return {"aa:bb:cc:dd:ee:ff": {"mac": "aa:bb:cc:dd:ee:ff"}}
        return {}

    def leases(self):
        return {
            "172.14.1.22": {
                "ip": "172.14.1.22",
                "mac": "aa:bb:cc:dd:ee:ff",
                "hostname": "VMC4041PB-1234",
            }
        }

    def start_pairing(self):
        self.started = True
        return CommandResult(True, "OK")


def test_known_database_camera_can_be_readded_when_it_associates_again():
    coordinator = PairingCoordinator(PairingSystem())
    session = coordinator.start()
    result = coordinator.status(session.identifier)

    assert result["wifi_detected"] is True
    assert result["dhcp_detected"] is True
    assert result["registered"] is True
    assert result["camera"]["serial"] == "AAKNOWN1234"
