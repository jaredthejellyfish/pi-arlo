import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_installer_never_reconfigures_ethernet_or_routing():
    files = [ROOT / "install.sh", *sorted((ROOT / "system").glob("*"))]
    text = "\n".join(path.read_text() for path in files)
    forbidden = [
        r"ip\s+addr\s+(?:add|flush).*eth0",
        r"ip\s+link\s+set\s+eth0",
        r"nmcli.*eth0",
        r"iptables",
        r"\bnft\b",
        r"ip_forward",
        r"\bbridge\b",
    ]
    for pattern in forbidden:
        assert not re.search(pattern, text, re.IGNORECASE), pattern


def test_only_wlan0_is_excluded_from_networkmanager():
    installer = (ROOT / "install.sh").read_text()
    assert "unmanaged-devices=interface-name:wlan0" in installer
    assert "unmanaged-devices=interface-name:eth0" not in installer


def test_hostapd_retains_sleeping_battery_cameras():
    installer = (ROOT / "install.sh").read_text()

    assert "ap_max_inactivity=604800" in installer
    assert "disassoc_low_ack=0" in installer
    assert "bss_max_idle=0" in installer
    assert "skip_inactivity_poll=1" not in installer
