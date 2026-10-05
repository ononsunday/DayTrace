"""启动打包程序并只捕获它自己的窗口，使用一次性数据目录。"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from PySide6.QtGui import QImage


def capture(process, target):
    user = ctypes.WinDLL("user32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetWindow.restype = wintypes.HWND
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowDC.argtypes = [wintypes.HWND]
    user.GetWindowDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user.PrintWindow.restype = wintypes.BOOL
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi.SelectObject.restype = wintypes.HGDIOBJ
    gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                             wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]

    windows = []
    def inspect(hwnd, parameter):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == process.pid and user.IsWindowVisible(hwnd) and not user.GetWindow(hwnd, 4):
            windows.append(hwnd)
        return True
    callback = callback_type(inspect)
    user.EnumWindows(callback, 0)
    if not windows or process.poll() is not None:
        raise RuntimeError("测试实例没有可捕获的主窗口")
    hwnd = windows[0]
    owner = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    if owner.value != process.pid:
        raise RuntimeError("窗口归属已变化，停止捕获")
    rect = wintypes.RECT()
    if not user.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if not 100 <= width <= 5000 or not 100 <= height <= 5000:
        raise RuntimeError("测试窗口尺寸异常")
    source = user.GetWindowDC(hwnd)
    memory = gdi.CreateCompatibleDC(source)
    bitmap = gdi.CreateCompatibleBitmap(source, width, height)
    if not source or not memory or not bitmap:
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory:
            gdi.DeleteDC(memory)
        if source:
            user.ReleaseDC(hwnd, source)
        raise RuntimeError("无法分配窗口捕获缓冲区")
    previous = gdi.SelectObject(memory, bitmap)
    try:
        # PrintWindow 让本窗口输出自身内容，不截取桌面或其它程序的覆盖区域。
        if not user.PrintWindow(hwnd, memory, 2):
            raise RuntimeError("测试窗口没有响应 PrintWindow")
        class Header(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG),
                        ("height", wintypes.LONG), ("planes", wintypes.WORD),
                        ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                        ("image_size", wintypes.DWORD), ("xppm", wintypes.LONG),
                        ("yppm", wintypes.LONG), ("used", wintypes.DWORD),
                        ("important", wintypes.DWORD)]
        header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        gdi.SelectObject(memory, previous)
        if gdi.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(header), 0) != height:
            raise RuntimeError("窗口像素读取不完整")
        image = QImage(pixels.raw, width, height, width * 4, QImage.Format.Format_RGB32).copy()
        target.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(target)):
            raise RuntimeError("窗口预览未保存")
        return {"width": width, "height": height, "screenshot": str(target), "only_test_window": True}
    finally:
        gdi.SelectObject(memory, previous)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(hwnd, source)


def main():
    # 使用物理像素读取窗口尺寸，避免 150% 缩放时只捕获左上区域。
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
    user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("qa-output/frozen-ui.png"))
    parser.add_argument("--report", type=Path, default=Path("qa-output/frozen-ui-report.json"))
    options = parser.parse_args()
    executable = options.exe.resolve()
    report = {"executable": str(executable), "production_data_used": False, "passed": False}
    with tempfile.TemporaryDirectory(prefix="daytrace-frozen-ui-") as directory:
        environment = os.environ.copy()
        environment.pop("QT_QPA_PLATFORM", None)
        environment["DAYTRACE_DATA_DIR"] = directory
        process = subprocess.Popen([str(executable), "--smoke-seconds", "10"], env=environment, cwd=executable.parent)
        try:
            time.sleep(4)
            report.update(capture(process, options.output.resolve()))
            code = process.wait(timeout=20)
            report["exit_code"] = code
            report["passed"] = code == 0
        except Exception as error:
            report["error"] = str(error)
        finally:
            if process.poll() is None:
                process.terminate()  # 仅结束本脚本创建的测试进程。
                process.wait(timeout=10)
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
