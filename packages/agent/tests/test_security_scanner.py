"""Tests for the security scanner. ALL system calls are mocked."""

from __future__ import annotations

from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from argus_agent.config import reset_settings
from argus_agent.events.bus import EventBus, reset_event_bus
from argus_agent.events.types import EventType


@pytest.fixture(autouse=True)
def _reset():
    reset_settings()
    reset_event_bus()
    yield
    reset_event_bus()
    reset_settings()


# Namedtuples to mimic psutil objects
Addr = namedtuple("Addr", ["ip", "port"])
Connection = namedtuple("Connection", ["status", "laddr", "raddr", "pid"])
ProcInfo = namedtuple("ProcInfo", ["pid", "name", "exe", "cmdline", "ppid"])


def _make_proc(pid, name, exe="", cmdline=None, ppid=1):
    """Create a mock process for psutil.process_iter."""
    mock = MagicMock()
    mock.info = {"pid": pid, "name": name, "exe": exe, "cmdline": cmdline or [], "ppid": ppid}
    return mock


def _make_scanner():
    """Create a SecurityScanner with mocked settings."""
    with patch("argus_agent.collectors.security_scanner.get_settings") as mock_settings:
        settings = MagicMock()
        settings.collector.host_root = ""
        mock_settings.return_value = settings
        from argus_agent.collectors.security_scanner import SecurityScanner
        return SecurityScanner(interval=300)


# ---- Open ports ----


@pytest.mark.asyncio
async def test_open_ports_baseline():
    """First scan records baseline, no events emitted."""
    scanner = _make_scanner()
    conns = [
        Connection(status="LISTEN", laddr=Addr("0.0.0.0", 22), raddr=None, pid=100),
        Connection(status="LISTEN", laddr=Addr("0.0.0.0", 80), raddr=None, pid=200),
    ]
    with patch("psutil.net_connections", return_value=conns):
        result = scanner._check_open_ports()

    assert 22 in result["listening_ports"]
    assert 80 in result["listening_ports"]
    assert len(result["events"]) == 0  # baseline recording


@pytest.mark.asyncio
async def test_open_ports_new_port_detected():
    """New port after baseline triggers NEW_OPEN_PORT event."""
    scanner = _make_scanner()

    # First scan: baseline
    conns1 = [Connection(status="LISTEN", laddr=Addr("0.0.0.0", 22), raddr=None, pid=100)]
    with patch("psutil.net_connections", return_value=conns1):
        scanner._check_open_ports()

    # Second scan: new port
    conns2 = [
        Connection(status="LISTEN", laddr=Addr("0.0.0.0", 22), raddr=None, pid=100),
        Connection(status="LISTEN", laddr=Addr("0.0.0.0", 4444), raddr=None, pid=999),
    ]
    with patch("psutil.net_connections", return_value=conns2):
        result = scanner._check_open_ports()

    assert len(result["events"]) == 1
    assert result["events"][0]["type"] == EventType.NEW_OPEN_PORT
    assert result["events"][0]["data"]["port"] == 4444


# ---- Failed SSH ----


@pytest.mark.asyncio
async def test_failed_ssh_brute_force(tmp_path):
    scanner = _make_scanner()
    auth_log = tmp_path / "auth.log"

    lines = []
    for i in range(15):
        lines.append(
            f"Jan 1 12:00:{i:02d} server sshd: "
            f"Failed password for root from 10.0.0.1 port 22 ssh2"
        )
    auth_log.write_text("\n".join(lines))

    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "read_text", return_value=auth_log.read_text()):
        result = scanner._check_failed_ssh()

    assert result["failures_by_ip"]["10.0.0.1"] == 15
    assert len(result["events"]) == 1
    assert result["events"][0]["type"] == EventType.BRUTE_FORCE


@pytest.mark.asyncio
async def test_failed_ssh_no_log():
    scanner = _make_scanner()
    with patch.object(Path, "exists", return_value=False):
        result = scanner._check_failed_ssh()
    assert result["failures_by_ip"] == {}
    assert len(result["events"]) == 0


# ---- File permissions ----


@pytest.mark.asyncio
async def test_file_permissions_world_readable():
    scanner = _make_scanner()

    mock_stat = MagicMock()
    # 0o100644 = rw-r--r-- = mode "644" -> others=4 (world-readable)
    mock_stat.st_mode = 0o100644

    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat", return_value=mock_stat):
        result = scanner._check_file_permissions()

    # shadow is world-readable with mode 644 -> event
    shadow_events = [e for e in result["events"] if e["data"]["path"] == "/etc/shadow"]
    assert len(shadow_events) == 1
    assert shadow_events[0]["type"] == EventType.PERMISSION_RISK


@pytest.mark.asyncio
async def test_file_permissions_secure():
    scanner = _make_scanner()

    mock_stat = MagicMock()
    mock_stat.st_mode = 0o100600  # rw------- = mode "600" -> secure

    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat", return_value=mock_stat):
        result = scanner._check_file_permissions()

    assert len(result["events"]) == 0


# ---- Suspicious processes ----


@pytest.mark.asyncio
async def test_suspicious_process_known_bad():
    scanner = _make_scanner()
    procs = [_make_proc(999, "xmrig", "/tmp/xmrig")]

    with patch("psutil.process_iter", return_value=procs):
        result = scanner._check_suspicious_processes()

    assert len(result["suspicious"]) == 1
    assert result["events"][0]["type"] == EventType.SUSPICIOUS_PROCESS


@pytest.mark.asyncio
async def test_suspicious_process_deleted_binary():
    scanner = _make_scanner()
    procs = [_make_proc(888, "malware", "/usr/bin/malware (deleted)")]

    with patch("psutil.process_iter", return_value=procs):
        result = scanner._check_suspicious_processes()

    assert len(result["suspicious"]) == 1
    assert "deleted_binary" in result["suspicious"][0]["reason"]


@pytest.mark.asyncio
async def test_no_suspicious_processes():
    scanner = _make_scanner()
    procs = [_make_proc(1, "systemd", "/sbin/init")]

    with patch("psutil.process_iter", return_value=procs):
        result = scanner._check_suspicious_processes()

    assert len(result["suspicious"]) == 0
    assert len(result["events"]) == 0


# ---- New executables ----


@pytest.mark.asyncio
async def test_new_executable_detected(tmp_path):
    scanner = _make_scanner()

    # First scan: baseline with no executables
    with patch.object(Path, "exists", return_value=False):
        scanner._check_new_executables()

    # Create mock scandir entries
    entry1 = MagicMock()
    entry1.is_file.return_value = True
    entry1.path = "/tmp/evil"
    entry1.stat.return_value = MagicMock(st_mode=0o100755)

    scanner._known_executables = set()  # Reset so first scan records baseline

    with patch.object(Path, "exists", return_value=True), \
         patch("os.scandir", return_value=[entry1]):
        scanner._check_new_executables()  # baseline

    entry2 = MagicMock()
    entry2.is_file.return_value = True
    entry2.path = "/tmp/new_evil"
    entry2.stat.return_value = MagicMock(st_mode=0o100755)

    with patch.object(Path, "exists", return_value=True), \
         patch("os.scandir", return_value=[entry1, entry2]):
        result = scanner._check_new_executables()

    assert len(result["events"]) == 1
    assert result["events"][0]["type"] == EventType.NEW_EXECUTABLE


# ---- Outbound connections ----


@pytest.mark.asyncio
async def test_outbound_connection_new():
    scanner = _make_scanner()

    # Baseline
    conns1 = [
        Connection(
            status="ESTABLISHED", laddr=Addr("10.0.0.1", 12345),
            raddr=Addr("8.8.8.8", 443), pid=100,
        ),
    ]
    with patch("psutil.net_connections", return_value=conns1):
        scanner._check_outbound_connections()

    # New connection
    conns2 = [
        Connection(
            status="ESTABLISHED", laddr=Addr("10.0.0.1", 12345),
            raddr=Addr("8.8.8.8", 443), pid=100,
        ),
        Connection(
            status="ESTABLISHED", laddr=Addr("10.0.0.1", 54321),
            raddr=Addr("1.2.3.4", 6667), pid=999,
        ),
    ]
    with patch("psutil.net_connections", return_value=conns2):
        result = scanner._check_outbound_connections()

    assert len(result["events"]) == 1
    assert result["events"][0]["type"] == EventType.SUSPICIOUS_OUTBOUND
    assert result["events"][0]["data"]["ip"] == "1.2.3.4"


# ---- Full scan ----


@pytest.mark.asyncio
async def test_scan_once_publishes_events():
    scanner = _make_scanner()
    bus = EventBus()

    published: list = []
    bus.subscribe(lambda e: published.append(e))

    procs = [_make_proc(999, "xmrig")]

    with patch("argus_agent.collectors.security_scanner.get_event_bus", return_value=bus), \
         patch("psutil.net_connections", return_value=[]), \
         patch.object(Path, "exists", return_value=False), \
         patch("psutil.process_iter", return_value=procs), \
         patch("os.scandir", return_value=[]):
        results = await scanner.scan_once()

    assert "checks" in results
    # At least one event should have been published (suspicious process)
    assert len(published) > 0
