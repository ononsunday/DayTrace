"""原生打包程序的单实例验证；仅使用一次性独立数据目录。"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time


PROJECT = Path(__file__).resolve().parents[1]


def run(executable: Path) -> dict:
    if sys.platform != "win32":
        raise RuntimeError("此验证仅支持 Windows")
    if not executable.is_file():
        raise RuntimeError("打包程序尚不存在")
    report = {"generated_at": datetime.now().astimezone().isoformat(), "executable": str(executable),
              "production_data_used": False, "captured_windows_titles_urls": False, "passed": False}
    first = second = None
    temporary_path = None
    temporary_handle = None
    try:
        temporary_handle = tempfile.TemporaryDirectory(prefix="daytrace-instance-", ignore_cleanup_errors=True)
        with temporary_handle as temp:
            temporary_path = Path(temp)
            database = temporary_path / "daytrace.sqlite3"
            environment = os.environ.copy()
            environment.pop("QT_QPA_PLATFORM", None)
            environment["DAYTRACE_DATA_DIR"] = str(temporary_path)
            arguments = [str(executable), "--hidden", "--smoke-seconds", "10"]
            started = time.monotonic()
            first = subprocess.Popen(arguments, env=environment, cwd=executable.parent,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = started + 20
            while not database.is_file():
                if first.poll() is not None:
                    raise RuntimeError("第一个实例在创建数据库前退出")
                if time.monotonic() >= deadline:
                    raise RuntimeError("第一个实例启动超时")
                time.sleep(0.05)
            time.sleep(0.7)
            second_started = time.monotonic()
            second = subprocess.Popen(arguments, env=environment, cwd=executable.parent,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            second_code = second.wait(timeout=8)
            second_elapsed = time.monotonic() - second_started
            first_still_alive = first.poll() is None
            first_code = first.wait(timeout=20)
            elapsed = time.monotonic() - started
            connection = sqlite3.connect(database)
            try:
                total, count = connection.execute("SELECT COALESCE(SUM(seconds),0),COUNT(*) FROM sessions").fetchone()
                app_count = connection.execute("SELECT COUNT(*) FROM apps").fetchone()[0]
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                connection.close()
            report.update({
                "first_exit_code": first_code, "second_exit_code": second_code,
                "second_exit_seconds": second_elapsed, "first_alive_when_second_exited": first_still_alive,
                "first_elapsed_seconds": elapsed, "database_total_seconds": total,
                "session_count": count, "app_count": app_count, "database_integrity": integrity,
                "allowed_maximum_seconds": elapsed + 2,
            })
            report["checks"] = {
                "first_normal_exit": first_code == 0,
                "second_normal_exit": second_code == 0,
                "second_exits_quickly": second_elapsed < 5,
                "first_remains_running": first_still_alive,
                "aggregate_time_not_doubled": total <= elapsed + 2,
                "sqlite_integrity_ok": integrity == "ok",
            }
            report["passed"] = all(report["checks"].values())
    except Exception as error:
        report["error"] = str(error)
    finally:
        # 只终止本测试自己创建的进程，不搜索或终止用户现有 DayTrace。
        for process in (second, first):
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        report["test_processes_stopped"] = all(process is None or process.poll() is not None for process in (first, second))
        if temporary_handle is not None:
            # 异常路径可能先遇到占用文件；停止自己创建的进程后再清理一次。
            temporary_handle.cleanup()
        if temporary_path is not None:
            report["temporary_data_removed"] = not temporary_path.exists()
        report["passed"] = report["passed"] and report["test_processes_stopped"] and report.get("temporary_data_removed", True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="DayTrace 打包程序双启动测试")
    parser.add_argument("--exe", type=Path, default=PROJECT / "dist" / "DayTrace" / "DayTrace.exe")
    parser.add_argument("--report", type=Path, default=PROJECT / "qa-output" / "instance-report.json")
    options = parser.parse_args()
    try:
        report = run(options.exe.resolve())
    except Exception as error:
        report = {"passed": False, "error": str(error), "production_data_used": False}
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(options.report)}, ensure_ascii=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
