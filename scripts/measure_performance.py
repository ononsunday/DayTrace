"""测量独立程序的工作集、私有内存、CPU 时间，不依赖 psutil。"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import statistics
import subprocess
import time


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


class TestProcessWindows:
    """只查询测试 PID 的窗口，不读取标题，也不操作其他实例。"""
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = [self.callback_type, wintypes.LPARAM]
        self.user.EnumWindows.restype = wintypes.BOOL
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.IsWindowVisible.restype = wintypes.BOOL
        self.user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user.GetWindow.restype = wintypes.HWND
        self.user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user.PostMessageW.restype = wintypes.BOOL

    def visible_main_windows(self, pid):
        windows = []
        def inspect(hwnd, parameter):
            owner_pid = wintypes.DWORD()
            thread = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            if thread and owner_pid.value == pid:
                # 无 owner 的可见顶层窗口作为主窗口，排除托盘及菜单窗口。
                if self.user.IsWindowVisible(hwnd) and not self.user.GetWindow(hwnd, 4):  # GW_OWNER
                    windows.append(hwnd)
            return True
        callback = self.callback_type(inspect)
        if not self.user.EnumWindows(callback, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return windows

    def close_to_tray(self, process):
        windows = self.visible_main_windows(process.pid)
        if not windows or process.poll() is not None:
            raise RuntimeError("未找到测试实例的可见主窗口，不能验证打开后隐藏状态")
        hwnd = windows[0]
        owner_pid = wintypes.DWORD()
        thread = self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if not thread or owner_pid.value != process.pid or process.poll() is not None:
            raise RuntimeError("测试窗口归属已变化，停止发送关闭消息")
        # 只向刚核实的测试窗口发送关闭事件，让 DayTrace 自己执行隐藏逻辑。
        if not self.user.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE
            raise ctypes.WinError(ctypes.get_last_error())
        deadline = time.monotonic() + 5
        while self.visible_main_windows(process.pid):
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("测试实例关闭后未保持后台运行并隐藏窗口")
            time.sleep(0.1)
        if process.poll() is not None:
            raise RuntimeError("测试实例关闭窗口后退出，未进入托盘")


def measure(command, seconds, hidden, directory, *, start_visible_then_hide=False):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    env = os.environ.copy()
    env["DAYTRACE_DATA_DIR"] = str(directory)
    # 第三种状态额外留出关闭事件等待和稳定时间，避免自动退出打断采样。
    args = [*command, "--smoke-seconds", str(seconds + (18 if start_visible_then_hide else 8))]
    if hidden:
        args.append("--hidden")
    process = subprocess.Popen(args, env=env)
    handle = kernel.OpenProcess(0x1010, False, process.pid)
    if not handle:
        process.terminate()
        raise ctypes.WinError(ctypes.get_last_error())
    samples = []
    def cpu_time():
        birth, exit_time, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(birth), ctypes.byref(exit_time), ctypes.byref(system), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        return sum((v.dwHighDateTime << 32) | v.dwLowDateTime for v in (system, user)) / 10_000_000
    try:
        time.sleep(5)
        windows = TestProcessWindows()
        if process.poll() is not None:
            raise RuntimeError(f"测试程序预热期间退出：{process.returncode}")
        if start_visible_then_hide:
            windows.close_to_tray(process)
            time.sleep(2)
        visible = bool(windows.visible_main_windows(process.pid))
        measured_hidden = hidden or start_visible_then_hide
        if process.poll() is not None:
            raise RuntimeError(f"测试程序采样前退出：{process.returncode}")
        if visible == measured_hidden:
            raise RuntimeError("测试窗口可见状态与请求的测量状态不符")
        start = time.monotonic()
        initial_cpu = cpu_time()
        while time.monotonic() - start < seconds:
            if process.poll() is not None:
                raise RuntimeError(f"测试程序提前退出：{process.returncode}")
            counters = PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            samples.append({"working_set_mb": counters.WorkingSetSize / 1048576, "private_mb": counters.PrivateUsage / 1048576})
            time.sleep(1)
        elapsed = time.monotonic() - start
        cpu = (cpu_time() - initial_cpu) / elapsed * 100
        state = "start_visible_then_hide" if start_visible_then_hide else "hidden" if hidden else "visible"
        return {"state": state, "hidden": measured_hidden, "start_visible_then_hide": start_visible_then_hide,
                "started_hidden": hidden, "window_hidden_before_measurement": not visible,
                "process_alive_before_measurement": True,
                "duration_seconds": round(elapsed, 2), "samples": len(samples),
                "average_working_set_mb": round(statistics.mean(s["working_set_mb"] for s in samples), 2),
                "peak_working_set_mb": round(max(s["working_set_mb"] for s in samples), 2),
                "average_private_mb": round(statistics.mean(s["private_mb"] for s in samples), 2),
                "cpu_percent_of_one_core": round(cpu, 3),
                "cpu_percent_of_machine": round(cpu / (os.cpu_count() or 1), 4)}
    finally:
        kernel.CloseHandle(handle)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--output", default="qa-output/performance.json")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    executable = Path(args.exe).resolve()
    command = [str(executable)]
    report = {"executable": str(executable), "logical_processors": os.cpu_count(),
              "notes": "分别测量隐藏启动、首页打开、首页打开后关闭到托盘。启动5秒预热，关闭到托盘后另稳定2秒，再每秒取样。CPU按进程时间增量计算；短时结果不能证明长期稳定性。", "results": []}
    for state in ("hidden", "visible", "start_visible_then_hide"):
        result = measure(command, max(5, args.seconds), state == "hidden",
                         output.parent / ("perf-" + state.replace("_", "-")),
                         start_visible_then_hide=state == "start_visible_then_hide")
        report["results"].append(result)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
