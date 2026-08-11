from pathlib import Path

import pytest
import yaml

from arlo_manager.configuration import (
    BEGIN,
    END,
    ConfigurationError,
    ConfigurationManager,
)
from arlo_manager.models import Camera
from arlo_manager.settings import Settings
from arlo_manager.store import StateStore
from arlo_manager.system import CommandResult


class FakeSystem:
    def __init__(self, fail_stream=False):
        self.commands = []
        self.fail_stream = fail_stream

    def run(self, args, timeout=8):
        self.commands.append(args)
        return CommandResult(True, "syntax check OK")

    def test_stream(self, slug):
        return CommandResult(not self.fail_stream, "")


def camera(serial="AA123456ABCDE", slug="driveway"):
    return Camera.from_dict(
        serial,
        {
            "name": "Driveway",
            "slug": slug,
            "mac": "aa:bb:cc:dd:ee:ff",
            "ip": "172.14.1.22",
            "hostname": "VMC4041PB-ABCDE",
        },
    )


def settings_for(tmp_path: Path) -> Settings:
    dns = tmp_path / "arlo.conf"
    media = tmp_path / "mediamtx.yml"
    dns.write_text(
        "interface=wlan0\ndhcp-range=172.14.1.10,172.14.1.99,255.255.255.0,24h\n"
    )
    media.write_text("logLevel: info\npaths:\n  unrelated:\n    source: publisher\n")
    return Settings(
        state_path=tmp_path / "state.json",
        dnsmasq_path=dns,
        mediamtx_path=media,
        leases_path=tmp_path / "leases",
        backup_dir=tmp_path / "backups",
    )


def test_dnsmasq_managed_block_is_replaced_without_duplication():
    first = camera()
    original = (
        f"interface=wlan0\n{BEGIN}\n# old\ndhcp-host={first.mac},172.14.1.40\n{END}\n"
    )
    result = ConfigurationManager._dnsmasq_text(original, {first.serial: first})
    assert result.count(BEGIN) == 1
    assert result.count(first.mac) == 1
    assert "172.14.1.22" in result
    assert "172.14.1.40" not in result


def test_apply_preserves_unrelated_media_paths_and_saves_state(tmp_path):
    config = settings_for(tmp_path)
    fake = FakeSystem()
    store = StateStore(config.state_path)
    manager = ConfigurationManager(config, store, fake)
    item = camera()

    manager.apply({item.serial: item}, test_slug=item.slug)

    media = yaml.safe_load(config.mediamtx_path.read_text())
    assert media["paths"]["unrelated"]["source"] == "publisher"
    assert media["paths"]["driveway"]["sourceOnDemand"] is True
    assert store.get(item.serial) == item
    assert ["systemctl", "restart", "dnsmasq"] in fake.commands
    assert ["systemctl", "restart", "mediamtx"] in fake.commands


def test_apply_rolls_back_both_live_files_when_stream_fails(tmp_path):
    config = settings_for(tmp_path)
    original_dns = config.dnsmasq_path.read_text()
    original_media = config.mediamtx_path.read_text()
    manager = ConfigurationManager(
        config, StateStore(config.state_path), FakeSystem(fail_stream=True)
    )

    with pytest.raises(ConfigurationError, match="could not be opened"):
        manager.apply({camera().serial: camera()}, test_slug="driveway")

    assert config.dnsmasq_path.read_text() == original_dns
    assert config.mediamtx_path.read_text() == original_media
    assert not config.state_path.exists()


def test_removal_drops_a_legacy_reservation_outside_managed_markers():
    item = camera()
    original = f"interface=wlan0\ndhcp-host={item.mac},{item.ip}\n"
    result = ConfigurationManager._dnsmasq_text(original, {}, removed_macs={item.mac})
    assert item.mac not in result
