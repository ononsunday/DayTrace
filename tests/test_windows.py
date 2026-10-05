from datetime import datetime, timezone
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from daytrace.platform.windows import (
    ProcessInfo,
    UNKNOWN_APP,
    WindowsDetector,
    autostart_command,
    executable_identity,
    idle_seconds_from_ticks,
    is_autostart,
    set_autostart,
)


class FakeApi:
    available = True
    hwnd = 100
    pid = 5
    birth = 10
    path = r"C:\Apps\Code.exe"
    idle = 1.5

    def __init__(self):
        self.calls = []
        self.after_resolve = None

    def input_available(self):
        return self.available

    def foreground_window(self):
        return self.hwnd

    def window_pid(self, hwnd):
        return self.pid

    def process_info(self, pid, known_creation):
        self.calls.append((pid, known_creation))
        info = None if self.path is None else ProcessInfo(self.birth, None if known_creation == self.birth else self.path)
        if self.after_resolve:
            self.after_resolve(self)
        return info

    def idle_seconds(self):
        return self.idle


def detector(api, **kwargs):
    return WindowsDetector(api, own_pid=999, monotonic=lambda: 10, wall=lambda: datetime(2026, 10, 3, tzinfo=timezone.utc), **kwargs)


def test_normal_path_and_two_windows_same_app():
    api = FakeApi()
    poller = detector(api)
    first = poller.sample()
    api.hwnd, api.pid, api.path = 101, 6, r"c:\apps\CODE.exe"
    second = poller.sample()
    assert first.app.key == second.app.key == r"c:\apps\code.exe"
    assert first.app.name == "Visual Studio Code"
    assert second.available and second.idle_seconds == 1.5


def test_own_process_is_excluded_before_resolving():
    api = FakeApi()
    api.pid = 999
    assert detector(api).sample().app is None
    assert api.calls == []


@pytest.mark.parametrize("hwnd,pid", [(0, 5), (100, 0)])
def test_missing_foreground_information_is_not_an_unknown_usage(hwnd, pid):
    api = FakeApi()
    api.hwnd, api.pid = hwnd, pid
    sample = detector(api).sample()
    assert sample.app is None and sample.available


def test_access_denied_is_known_unknown_identity_not_pid_fragment():
    api = FakeApi()
    api.path = None
    poller = detector(api)
    assert poller.sample().app == UNKNOWN_APP
    api.pid = 6
    assert poller.sample().app == UNKNOWN_APP


def test_secure_or_inaccessible_desktop_has_no_usage():
    api = FakeApi()
    api.available = False
    sample = detector(api).sample()
    assert sample.app is None and sample.available is False
    assert api.calls == []


@pytest.mark.parametrize("change", [lambda api: setattr(api, "hwnd", 200), lambda api: setattr(api, "pid", 7)])
def test_switch_during_resolution_discards_racy_sample(change):
    api = FakeApi()
    api.after_resolve = change
    assert detector(api).sample().app is None


def test_secure_desktop_appearing_during_resolution_is_unavailable():
    api = FakeApi()
    api.after_resolve = lambda api: setattr(api, "available", False)
    assert detector(api).sample().available is False


def test_creation_time_prevents_pid_reuse():
    api = FakeApi()
    poller = detector(api)
    assert poller.sample().app.name == "Visual Studio Code"
    assert poller.sample().app.name == "Visual Studio Code"
    assert api.calls[-1] == (5, 10)
    api.birth, api.path = 20, r"C:\Apps\chrome.exe"
    assert poller.sample().app.name == "Google Chrome"


def test_cache_is_bounded():
    api = FakeApi()
    poller = detector(api, cache_size=3)
    for pid in range(10, 20):
        api.pid = pid
        poller.sample()
    assert len(poller._cache) == 3
    assert list(poller._cache) == [17, 18, 19]


def test_cache_expires_after_thirty_seconds_even_with_frequent_samples():
    api = FakeApi()
    current = [0]
    poller = WindowsDetector(api, own_pid=999, monotonic=lambda: current[0], cache_ttl=60)
    poller.sample()
    current[0] = 29
    poller.sample()
    assert api.calls[-1][1] == 10
    current[0] = 30
    poller.sample()
    assert api.calls[-1][1] is None


def test_detection_exception_fails_closed():
    api = FakeApi()
    api.input_available = lambda: 1 / 0
    sample = detector(api).sample()
    assert sample.app is None and not sample.available


@pytest.mark.parametrize("now,last,expected", [(7000, 2000, 5), (0x1_0000_0800, 0xFFFFFC00, 3.072), (0x2_0000_0200, 0xFFFFFE00, 1.024)])
def test_idle_ticks_handle_32_bit_rollover(now, last, expected):
    assert idle_seconds_from_ticks(now, last) == pytest.approx(expected)


def test_applicationframehost_is_not_fabricated_as_a_hosted_app():
    assert executable_identity(r"C:\Windows\System32\ApplicationFrameHost.exe").name == "Windows 应用容器"


def test_frozen_autostart_quotes_spaces_and_starts_hidden(monkeypatch):
    import daytrace.platform.windows as windows
    monkeypatch.setattr(windows.sys, "frozen", True, raising=False)
    monkeypatch.setattr(windows.sys, "executable", r"C:\My Apps\DayTrace.exe")
    assert autostart_command() == '"C:\\My Apps\\DayTrace.exe" --hidden'


def test_source_autostart_uses_project_entrypoint():
    command = autostart_command()
    assert "run_daytrace.py" in command and command.endswith("--hidden")


def test_autostart_writes_only_current_user_and_removes_explicitly(monkeypatch):
    import daytrace.platform.windows as windows
    writes, deletes, opens = [], [], []
    def open_key(hive, path, reserved, access):
        opens.append((hive, path, access))
        return nullcontext("test-key")
    fake_registry = SimpleNamespace(
        HKEY_CURRENT_USER="current-user", KEY_SET_VALUE=2, KEY_READ=1, REG_SZ=1,
        CreateKeyEx=open_key, OpenKey=open_key,
        SetValueEx=lambda *args: writes.append(args),
        DeleteValue=lambda *args: deletes.append(args),
        QueryValueEx=lambda *args: ("existing-command", 1),
    )
    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setitem(windows.sys.modules, "winreg", fake_registry)
    monkeypatch.setattr(windows, "autostart_command", lambda: '"DayTrace.exe" --hidden')
    set_autostart(True)
    assert writes == [("test-key", "DayTrace", 0, 1, '"DayTrace.exe" --hidden')]
    assert is_autostart()
    set_autostart(False)
    assert deletes == [("test-key", "DayTrace")]
    assert all(hive == "current-user" for hive, _, _ in opens)


def test_disabling_missing_autostart_is_harmless(monkeypatch):
    import daytrace.platform.windows as windows
    def missing(*args):
        raise FileNotFoundError()
    fake_registry = SimpleNamespace(
        HKEY_CURRENT_USER="current-user", KEY_SET_VALUE=2, KEY_READ=1, REG_SZ=1,
        CreateKeyEx=lambda *args: nullcontext("test-key"),
        OpenKey=missing, DeleteValue=missing,
    )
    monkeypatch.setattr(windows.sys, "platform", "win32")
    monkeypatch.setitem(windows.sys.modules, "winreg", fake_registry)
    set_autostart(False)
    assert is_autostart() is False
