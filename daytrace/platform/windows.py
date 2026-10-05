"""Windows 前台检测与当前用户自启动设置。

只读取窗口句柄、进程路径和最后输入时间，不读取窗口标题或输入内容。
DLL 在首次采样时加载，便于在非 Windows 平台测试统计逻辑。
"""

from __future__ import annotations

import ctypes
import ntpath
import os
import subprocess
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from daytrace.core.models import AppIdentity, Observation


_DISPLAY_NAMES = {
    "code.exe": "Visual Studio Code",
    "chrome.exe": "Google Chrome",
    "msedge.exe": "Microsoft Edge",
    "firefox.exe": "Firefox",
    "wechat.exe": "微信",
    "weixin.exe": "微信",
    "qq.exe": "QQ",
    "explorer.exe": "文件资源管理器",
    "notepad.exe": "记事本",
    "winword.exe": "Microsoft Word",
    "excel.exe": "Microsoft Excel",
    "powerpnt.exe": "Microsoft PowerPoint",
    "outlook.exe": "Microsoft Outlook",
    "devenv.exe": "Visual Studio",
    "pycharm64.exe": "PyCharm",
    "idea64.exe": "IntelliJ IDEA",
    "vlc.exe": "VLC",
    "cloudmusic.exe": "网易云音乐",
    "applicationframehost.exe": "Windows 应用容器",
}

UNKNOWN_APP = AppIdentity("unknown", "未知应用")


def executable_identity(executable: str) -> AppIdentity:
    """同一路径的不同窗口/PID 合为一个应用；不把窗口标题作为标识。"""
    normalized = ntpath.normpath(executable)
    basename = ntpath.basename(normalized)
    name = _DISPLAY_NAMES.get(basename.casefold(), ntpath.splitext(basename)[0])
    return AppIdentity(normalized.casefold(), name or "未知应用", normalized)


def idle_seconds_from_ticks(now_ticks: int, last_input_ticks: int) -> float:
    """LASTINPUTINFO 是 32 位计数器，约每 49.7 天回绕一次。"""
    return ((now_ticks - last_input_ticks) & 0xFFFFFFFF) / 1000.0


@dataclass(frozen=True)
class ProcessInfo:
    creation_id: int | None
    executable: str | None


class _Api(Protocol):
    def input_available(self) -> bool: ...
    def foreground_window(self) -> int: ...
    def window_pid(self, hwnd: int) -> int: ...
    def process_info(self, pid: int, known_creation: int | None) -> ProcessInfo | None: ...
    def idle_seconds(self) -> float | None: ...


@dataclass(frozen=True)
class _CacheEntry:
    identity: AppIdentity
    creation_id: int
    checked_at: float


class WindowsDetector:
    """采样期间发生窗口切换时放弃归属，避免把不确定时间计给某应用。"""

    def __init__(
        self,
        api: _Api | None = None,
        *,
        own_pid: int | None = None,
        monotonic: Callable[[], float] | None = None,
        wall: Callable[[], datetime] | None = None,
        cache_size: int = 128,
        cache_ttl: float = 30.0,
    ) -> None:
        self._api = api
        self._own_pid = os.getpid() if own_pid is None else own_pid
        self._monotonic = monotonic or time.monotonic
        self._wall = wall or (lambda: datetime.now().astimezone())
        self._cache_size = max(1, cache_size)
        self._cache_ttl = min(30.0, max(0.0, cache_ttl))
        self._cache: OrderedDict[int, _CacheEntry] = OrderedDict()

    def _identity(self, pid: int, now: float) -> AppIdentity:
        # 每次查询进程创建时间，防止 Windows 重用 PID 后沿用旧应用。
        entry = self._cache.get(pid)
        if entry is not None and now - entry.checked_at >= self._cache_ttl:
            self._cache.pop(pid, None)
            entry = None
        info = self._api.process_info(pid, entry.creation_id if entry else None)
        if info is None:
            self._cache.pop(pid, None)
            return UNKNOWN_APP
        if entry is not None and info.creation_id == entry.creation_id:
            self._cache.move_to_end(pid)
            return entry.identity
        if not info.executable:
            self._cache.pop(pid, None)
            return UNKNOWN_APP
        identity = executable_identity(info.executable)
        if info.creation_id is not None:
            self._cache[pid] = _CacheEntry(identity, info.creation_id, now)
            self._cache.move_to_end(pid)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        else:
            self._cache.pop(pid, None)
        return identity

    def sample(self) -> Observation:
        now, wall = self._monotonic(), self._wall()
        try:
            if self._api is None:
                self._api = _NativeApi()
            # 锁屏、UAC 安全桌面或无法查询输入桌面时停止统计。
            if not self._api.input_available():
                return Observation(now, wall, None, None, False)
            idle = self._api.idle_seconds()
            hwnd = self._api.foreground_window()
            if not hwnd:
                return Observation(now, wall, None, idle)
            pid = self._api.window_pid(hwnd)
            if not pid:
                return Observation(now, wall, None, idle)
            if pid == self._own_pid:
                return Observation(now, wall, None, idle)
            identity = self._identity(pid, now)
            # 进程路径查询可能耗时；二次核对窗口与 PID，丢弃竞态样本。
            if self._api.foreground_window() != hwnd or self._api.window_pid(hwnd) != pid:
                return Observation(now, wall, None, idle)
            if not self._api.input_available():
                return Observation(now, wall, None, None, False)
            return Observation(now, wall, identity, idle)
        except Exception:
            # 检测失败不能击穿常驻服务，失败样本也不能累计有效时间。
            return Observation(now, wall, None, None, False)


class _NativeApi:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("DayTrace 的窗口检测仅支持 Windows")
        from ctypes import wintypes

        self.wintypes = wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        self.LASTINPUTINFO = LASTINPUTINFO
        # 显式声明指针/句柄宽度，避免 Win64 默认 c_int 截断句柄。
        prototypes = (
            (self.user32.GetForegroundWindow, [], wintypes.HWND),
            (self.user32.GetWindowThreadProcessId, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            (self.user32.GetLastInputInfo, [ctypes.POINTER(LASTINPUTINFO)], wintypes.BOOL),
            (self.user32.OpenInputDesktop, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            (self.user32.GetUserObjectInformationW, [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            (self.user32.CloseDesktop, [wintypes.HANDLE], wintypes.BOOL),
            (self.kernel32.GetTickCount64, [], ctypes.c_ulonglong),
            (self.kernel32.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            (self.kernel32.QueryFullProcessImageNameW, [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            (self.kernel32.GetProcessTimes, [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)], wintypes.BOOL),
            (self.kernel32.CloseHandle, [wintypes.HANDLE], wintypes.BOOL),
        )
        for function, arguments, result in prototypes:
            function.argtypes, function.restype = arguments, result

    def input_available(self) -> bool:
        desktop = self.user32.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS
        if not desktop:
            return False
        available = False
        try:
            buffer = ctypes.create_unicode_buffer(256)
            required = self.wintypes.DWORD()
            if self.user32.GetUserObjectInformationW(desktop, 2, buffer, ctypes.sizeof(buffer), ctypes.byref(required)):
                available = buffer.value.casefold() == "default"
        finally:
            if not self.user32.CloseDesktop(desktop):
                available = False
        return available

    def foreground_window(self) -> int:
        return int(self.user32.GetForegroundWindow() or 0)

    def window_pid(self, hwnd: int) -> int:
        pid = self.wintypes.DWORD()
        thread = self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) if thread else 0

    def process_info(self, pid: int, known_creation: int | None) -> ProcessInfo | None:
        handle = self.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            creation, exit_time, kernel, user = (self.wintypes.FILETIME() for _ in range(4))
            birth = None
            if self.kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)):
                birth = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            if birth is not None and birth == known_creation:
                return ProcessInfo(birth, None)
            buffer = ctypes.create_unicode_buffer(32768)
            length = self.wintypes.DWORD(len(buffer))
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                return None
            return ProcessInfo(birth, buffer.value)
        finally:
            self.kernel32.CloseHandle(handle)

    def idle_seconds(self) -> float | None:
        info = self.LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not self.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        return idle_seconds_from_ticks(int(self.kernel32.GetTickCount64()), int(info.dwTime))


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_command() -> str:
    """源码使用 pythonw；打包版本直接执行 exe，并始终隐藏到托盘。"""
    if getattr(sys, "frozen", False):
        arguments = [sys.executable, "--hidden"]
    else:
        interpreter = Path(sys.executable)
        pythonw = interpreter.with_name("pythonw.exe")
        arguments = [str(pythonw if pythonw.exists() else interpreter), str(Path(__file__).resolve().parents[2] / "run_daytrace.py"), "--hidden"]
    return subprocess.list2cmdline(arguments)


def set_autostart(enabled: bool) -> None:
    """仅由用户主动切换设置时调用，不需要管理员权限。"""
    if sys.platform != "win32":
        raise OSError("开机自启动仅支持 Windows")
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, "DayTrace", 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, "DayTrace")
            except FileNotFoundError:
                pass


def is_autostart() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            command, kind = winreg.QueryValueEx(key, "DayTrace")
            return kind == winreg.REG_SZ and bool(command)
    except FileNotFoundError:
        return False
