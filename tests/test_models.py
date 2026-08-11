import pytest

from arlo_manager.models import Camera, slugify


def camera(**overrides):
    values = {
        "name": "Side Yard",
        "slug": "side_yard",
        "mac": "aa:bb:cc:dd:ee:ff",
        "ip": "172.14.1.22",
        "hostname": "VMC4041PB-ABCDE",
    }
    values.update(overrides)
    return Camera.from_dict("AA123456ABCDE", values)


def test_camera_accepts_private_arlo_address():
    assert camera().slug == "side_yard"


@pytest.mark.parametrize(
    "ip", ["192.168.1.5", "172.14.1.1", "172.14.1.0", "172.14.1.255"]
)
def test_camera_rejects_unsafe_address(ip):
    with pytest.raises(ValueError):
        camera(ip=ip)


@pytest.mark.parametrize("slug", ["Side Yard", "../camera", "side-yard", "side__yard"])
def test_camera_rejects_unsafe_slug(slug):
    with pytest.raises(ValueError):
        camera(slug=slug)


def test_slugify_is_safe_and_predictable():
    assert slugify(" Side Yard Camera! ") == "side_yard_camera"
