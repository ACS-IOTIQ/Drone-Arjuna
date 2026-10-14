"""Smart connect: one address -> every MAVLink link style probed together."""
import pytest
from pydantic import ValidationError

from app.modules.drone_control.auto_connector import build_target_candidates
from app.schemas.drone import AutoConnectRequest
from app.utils.mavlink_utils import build_connection_string


def test_target_candidates_cover_every_link_style():
    cands = build_target_candidates("10.0.0.1", 14550)
    assert [c["transport"] for c in cands] == ["udp_out", "tcp", "udp", "tcp_listen"]
    assert all(c["host"] == "10.0.0.1" and c["port"] == 14550 for c in cands)


def test_target_candidate_labels_are_unique():
    labels = [c["label"] for c in build_target_candidates("10.0.0.1", 14550)]
    assert len(set(labels)) == len(labels)


@pytest.mark.parametrize("transport,expected", [
    ("udp_out",    "udpout:10.0.0.1:14550"),
    ("tcp",        "tcp:10.0.0.1:14550"),
    ("udp",        "udpin:0.0.0.0:14550"),
    ("tcp_listen", "tcpin:0.0.0.0:14550"),
])
def test_every_target_transport_builds_a_connection_string(transport, expected):
    assert build_connection_string(transport, "10.0.0.1", 14550) == expected


def test_autoconnect_request_target_is_optional():
    req = AutoConnectRequest(drone_instance_id=1)
    assert req.host is None and req.port is None


def test_autoconnect_request_accepts_address():
    req = AutoConnectRequest(drone_instance_id=1, host="10.0.0.1", port=14550)
    assert (req.host, req.port) == ("10.0.0.1", 14550)


@pytest.mark.parametrize("host", ["10.0.0.1; rm -rf /", "a b", "udp://x", ""])
def test_autoconnect_request_rejects_odd_hosts(host):
    with pytest.raises(ValidationError):
        AutoConnectRequest(drone_instance_id=1, host=host, port=14550)


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_autoconnect_request_rejects_bad_ports(port):
    with pytest.raises(ValidationError):
        AutoConnectRequest(drone_instance_id=1, host="10.0.0.1", port=port)
