from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_unused_moq_listener_is_disabled_for_read_only_service():
    config = yaml.safe_load((ROOT / "config" / "mediamtx.yml").read_text())

    assert config["moq"] is False
