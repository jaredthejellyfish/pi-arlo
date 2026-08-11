import hashlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify-checksum.sh"


@pytest.mark.parametrize("marker", ["*", ""])
def test_verifier_accepts_binary_and_text_checksum_formats(tmp_path, marker):
    archive = tmp_path / "mediamtx_v1.20.0_linux_arm64.tar.gz"
    archive.write_bytes(b"verified MediaMTX fixture")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksums = tmp_path / "checksums.sha256"
    checksums.write_text(f"{digest} {marker}{archive.name}\n")

    result = subprocess.run(
        [VERIFIER, checksums, archive], text=True, capture_output=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{archive.name}: OK"


def test_verifier_rejects_a_mismatched_archive(tmp_path):
    archive = tmp_path / "mediamtx.tar.gz"
    archive.write_bytes(b"unexpected content")
    checksums = tmp_path / "checksums.sha256"
    checksums.write_text(f"{'0' * 64} *{archive.name}\n")

    result = subprocess.run(
        [VERIFIER, checksums, archive], text=True, capture_output=True, check=False
    )

    assert result.returncode == 1
    assert "Checksum mismatch" in result.stderr
