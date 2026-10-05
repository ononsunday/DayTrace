"""入口保留启动错误，方便没有控制台的发布版本排查依赖故障。"""
import os
from pathlib import Path
import sys
import traceback


def run():
    try:
        from daytrace.app import main
        return main()
    except Exception:
        message = traceback.format_exc()
        directory = Path(os.environ.get("DAYTRACE_DATA_DIR") or str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DayTrace"))
        try:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "startup-error.log").write_text(message, encoding="utf-8")
        except OSError:
            pass
        if sys.stderr is not None:
            sys.stderr.write(message)
        if "--smoke-seconds" not in sys.argv and sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"启动失败，请保留本地错误日志：\n{directory / 'startup-error.log'}", "DayTrace", 0x10)
        return 1

if __name__ == "__main__":
    raise SystemExit(run())
