"""本地 SQLite 数据层；所有统计写入在短事务中完成。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
import sqlite3
import threading
from typing import Iterable

from .models import AppIdentity, CATEGORIES, Segment


def _day(value: str | date) -> str:
    if isinstance(value, datetime):
        value = value.date()
    return date.fromisoformat(value).isoformat() if isinstance(value, str) else value.isoformat()


def default_category(app: AppIdentity) -> str:
    identifier = (app.key + " " + app.name + " " + Path(app.executable).name).lower()
    rules = (
        ("学习与编程", ("code.exe", "visual studio", "pycharm", "idea64", "python", "jupyter", "notepad++", "dev-c", "eclipse")),
        ("游戏娱乐", ("steam", "epicgames", "genshin", "starrail", "minecraft", "game", "游戏")),
        ("社交聊天", ("wechat", "weixin", "qq.exe", "discord", "telegram", "微信")),
        ("视频与音乐", ("music", "spotify", "vlc", "potplayer", "bilibili", "音乐")),
        ("工作办公", ("winword", "excel", "powerpnt", "wps", "outlook", "onenote")),
        ("系统工具", ("explorer", "taskmgr", "cmd.exe", "powershell", "terminal", "settings", "系统")),
    )
    for category, keywords in rules:
        if any(word in identifier for word in keywords):
            return category
    return "其他"


def split_segment(segment: Segment) -> Iterable[Segment]:
    """按本地午夜拆分，单调时钟秒数按墙钟区间比例分配。"""
    span = (segment.end - segment.start).total_seconds()
    if span <= 0 or segment.seconds <= 0 or not math.isfinite(segment.seconds):
        return
    cursor = segment.start
    remaining = segment.seconds
    while cursor.date() < segment.end.date():
        midnight = datetime.combine(cursor.date() + timedelta(days=1), time.min, tzinfo=cursor.tzinfo)
        seconds = segment.seconds * (midnight - cursor).total_seconds() / span
        yield Segment(segment.app, cursor, midnight, seconds, segment.mode, segment.ingestion_id)
        remaining -= seconds
        cursor = midnight
    if cursor < segment.end:
        yield Segment(segment.app, cursor, segment.end, max(0.0, remaining), segment.mode, segment.ingestion_id)


class Repository:
    _TABLE_COLUMNS = {
        "apps": ("key", "name", "executable", "category", "excluded", "icon"),
        "sessions": ("id", "app_key", "day", "start", "end", "seconds", "mode"),
        "receipts": ("signature", "day"),
        "diaries": ("date", "completed", "mood", "body", "tags"),
        "settings": ("key", "value"),
    }

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), timeout=10, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self._connection.close()
            raise ValueError("数据库版本高于当前 DayTrace 支持的版本，请使用对应版本的软件")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS apps (
                key TEXT PRIMARY KEY, name TEXT NOT NULL, executable TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '其他', excluded INTEGER NOT NULL DEFAULT 0,
                icon TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY, app_key TEXT NOT NULL REFERENCES apps(key),
                day TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
                seconds REAL NOT NULL CHECK(seconds > 0),
                mode TEXT NOT NULL CHECK(mode IN ('foreground', 'active'))
            );
            CREATE INDEX IF NOT EXISTS sessions_day ON sessions(day, start);
            CREATE TABLE IF NOT EXISTS receipts (signature TEXT PRIMARY KEY, day TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS receipts_day ON receipts(day);
            CREATE TABLE IF NOT EXISTS diaries (
                date TEXT PRIMARY KEY, completed TEXT NOT NULL DEFAULT '', mood TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            PRAGMA user_version=1;
        """)
        self._connection.commit()

    def append_segments(self, segments: Iterable[Segment]) -> None:
        with self._lock, self._connection:
            for original in segments:
                if original.mode not in ("foreground", "active"):
                    raise ValueError("未知统计模式")
                for segment in split_segment(original):
                    day = segment.start.date().isoformat()
                    start, end = segment.start.isoformat(), segment.end.isoformat()
                    payload = json.dumps([segment.app.key, start, end, segment.seconds, segment.mode, segment.ingestion_id], ensure_ascii=False)
                    signature = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                    # 摄取指纹与时间段同一事务提交；异常重试不会重复增加时间。
                    inserted = self._connection.execute(
                        "INSERT OR IGNORE INTO receipts(signature,day) VALUES(?,?)", (signature, day)
                    ).rowcount
                    if not inserted:
                        continue
                    app = segment.app
                    self._connection.execute(
                        "INSERT OR IGNORE INTO apps(key,name,executable,category) VALUES(?,?,?,?)",
                        (app.key, app.name or "未知应用", app.executable, default_category(app)),
                    )
                    if self.is_excluded(app.key):
                        continue
                    # 仅合并完全连续的边界，不跨过空闲、锁屏、休眠或重启后的间隙。
                    previous = self._connection.execute(
                        "SELECT id,app_key,end,mode FROM sessions WHERE day=? ORDER BY id DESC LIMIT 1", (day,)
                    ).fetchone()
                    if previous and previous["app_key"] == app.key and previous["end"] == start and previous["mode"] == segment.mode:
                        self._connection.execute(
                            "UPDATE sessions SET end=?,seconds=seconds+? WHERE id=?",
                            (end, segment.seconds, previous["id"]),
                        )
                    else:
                        self._connection.execute(
                            "INSERT INTO sessions(app_key,day,start,end,seconds,mode) VALUES(?,?,?,?,?,?)",
                            (app.key, day, start, end, segment.seconds, segment.mode),
                        )

    def get_setting(self, key: str, default=None):
        with self._lock:
            row = self._connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value"])
            except (ValueError, TypeError):
                return default

    def set_setting(self, key: str, value) -> None:
        serialized = json.dumps(value, ensure_ascii=False)
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, serialized),
            )

    def list_apps(self) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self._connection.execute("SELECT * FROM apps ORDER BY name COLLATE NOCASE")]

    def update_app(self, key: str, name=None, category=None, excluded=None, icon=None) -> None:
        values = {"name": name, "category": category, "excluded": excluded, "icon": icon}
        values = {field: value for field, value in values.items() if value is not None}
        if category is not None and category not in CATEGORIES:
            raise ValueError("未知分类")
        if excluded is not None:
            values["excluded"] = int(bool(excluded))
        if not values:
            return
        with self._lock, self._connection:
            self._connection.execute("INSERT OR IGNORE INTO apps(key,name) VALUES(?,?)", (key, name or key))
            assignments = ",".join(field + "=?" for field in values)
            self._connection.execute(f"UPDATE apps SET {assignments} WHERE key=?", (*values.values(), key))

    def is_excluded(self, key: str) -> bool:
        with self._lock:
            row = self._connection.execute("SELECT excluded FROM apps WHERE key=?", (key,)).fetchone()
            return bool(row and row["excluded"])

    def daily_summary(self, value: str | date) -> dict:
        day = _day(value)
        with self._lock:
            apps = [dict(row) for row in self._connection.execute("""
                SELECT a.key,a.name,a.category,a.icon,a.executable,SUM(s.seconds) AS seconds
                FROM sessions s JOIN apps a ON a.key=s.app_key WHERE s.day=?
                GROUP BY a.key ORDER BY seconds DESC
            """, (day,))]
            categories = [dict(row) for row in self._connection.execute("""
                SELECT a.category,SUM(s.seconds) AS seconds FROM sessions s
                JOIN apps a ON a.key=s.app_key WHERE s.day=? GROUP BY a.category ORDER BY seconds DESC
            """, (day,))]
            timeline = [dict(row) for row in self._connection.execute("""
                SELECT s.id,s.app_key,a.name,a.category,a.icon,a.executable,s.start,s.end,s.seconds,s.mode
                FROM sessions s JOIN apps a ON a.key=s.app_key WHERE s.day=? ORDER BY s.start,s.id
            """, (day,))]
            return {"date": day, "total": sum(app["seconds"] for app in apps), "apps": apps, "categories": categories, "timeline": timeline}

    def trend(self, end_date: str | date, days: int) -> list[dict]:
        end = date.fromisoformat(_day(end_date))
        if days < 1 or days > 3660:
            raise ValueError("趋势天数必须在 1～3660 之间")
        start = end - timedelta(days=days - 1)
        with self._lock:
            totals = dict(self._connection.execute(
                "SELECT day,SUM(seconds) FROM sessions WHERE day BETWEEN ? AND ? GROUP BY day", (start.isoformat(), end.isoformat())
            ).fetchall())
        return [{"date": (start + timedelta(days=i)).isoformat(), "seconds": totals.get((start + timedelta(days=i)).isoformat(), 0.0)} for i in range(days)]

    def get_diary(self, value: str | date) -> dict:
        day = _day(value)
        with self._lock:
            row = self._connection.execute("SELECT * FROM diaries WHERE date=?", (day,)).fetchone()
        if row:
            result = dict(row)
            try:
                result["tags"] = json.loads(result["tags"])
            except (ValueError, TypeError):
                result["tags"] = []
            return result
        return {"date": day, "completed": "", "mood": "", "body": "", "tags": []}

    def save_diary(self, value: str | date, completed: str, mood: str, body: str, tags) -> None:
        day = _day(value)
        if isinstance(tags, str):
            tags = [item.strip() for item in tags.replace("，", ",").split(",") if item.strip()]
        tags_json = json.dumps(list(tags), ensure_ascii=False)
        with self._lock, self._connection:
            self._connection.execute("""
                INSERT INTO diaries(date,completed,mood,body,tags) VALUES(?,?,?,?,?)
                ON CONFLICT(date) DO UPDATE SET completed=excluded.completed,mood=excluded.mood,body=excluded.body,tags=excluded.tags
            """, (day, completed, mood, body, tags_json))

    def export(self, path: str | Path, format: str = "json") -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if format not in ("json", "csv"):
            raise ValueError("只支持 JSON 或 CSV")
        if destination.resolve() == self.path.resolve():
            raise ValueError("导出文件不能覆盖正在使用的数据库")
        temp = destination.with_name(destination.name + ".daytrace-tmp")
        try:
            with self._lock, temp.open("w", encoding="utf-8-sig" if format == "csv" else "utf-8", newline="") as output:
                # 流式导出，不把多年历史一次装入内存。
                tables = ("sessions", "apps", "diaries", "settings")
                if format == "csv":
                    fields = [
                        "record_type", "id", "day", "date", "app_key", "key", "app_name", "name",
                        "category", "start", "end", "seconds", "mode", "executable", "excluded", "icon",
                        "completed", "mood", "body", "tags", "setting_key", "value",
                    ]
                    writer = csv.DictWriter(output, fieldnames=fields)
                    writer.writeheader()
                    automatic = self._connection.execute("""
                        SELECT s.*,a.name AS app_name,a.name,a.category,a.executable,a.excluded,a.icon
                        FROM sessions s JOIN apps a ON a.key=s.app_key ORDER BY s.day,s.start,s.id
                    """)
                    for source in automatic:
                        row = dict(source)
                        row["record_type"] = "automatic"
                        writer.writerow(self._csv_safe(row))
                    for table, kind in (("diaries", "diary"), ("apps", "app"), ("settings", "setting")):
                        for source in self._connection.execute(f"SELECT * FROM {table}"):
                            row = dict(source)
                            row["record_type"] = kind
                            if table == "diaries":
                                row["day"] = row["date"]
                            elif table == "apps":
                                row["app_key"] = row["key"]
                                row["app_name"] = row["name"]
                            else:
                                row["setting_key"] = row["key"]
                            writer.writerow(self._csv_safe(row))
                else:
                    output.write('{"schema_version":1')
                    for table in tables:
                        output.write("," + json.dumps(table) + ":[")
                        separator = ""
                        for row in self._connection.execute(f"SELECT * FROM {table}"):
                            output.write(separator + json.dumps(dict(row), ensure_ascii=False))
                            separator = ","
                        output.write("]")
                    output.write("}")
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _csv_safe(row: dict) -> dict:
        """保护 Excel 会当作公式解释的文本；JSON 导出保留原文。"""
        return {
            key: "'" + value
            if isinstance(value, str) and value.lstrip(" ").startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
            else value
            for key, value in row.items()
        }

    def backup(self, path: str | Path) -> None:
        destination = Path(path)
        if destination.resolve() == self.path.resolve():
            raise ValueError("备份文件不能覆盖正在使用的数据库")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(destination.name + ".daytrace-tmp")
        try:
            with self._lock:
                target = sqlite3.connect(temp)
                try:
                    self._connection.backup(target)
                finally:
                    target.close()
            os.replace(temp, destination)
        finally:
            temp.unlink(missing_ok=True)

    def restore(self, path: str | Path) -> None:
        source = Path(path).resolve()
        if source == self.path.resolve():
            raise ValueError("不能从当前正在使用的数据库恢复")
        if not source.is_file():
            raise ValueError("找不到备份数据库")
        validation = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        try:
            if validation.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("备份数据库已损坏")
            if validation.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise ValueError("不支持此备份版本")
            for table, columns in self._TABLE_COLUMNS.items():
                actual = {row[1] for row in validation.execute(f"PRAGMA table_info({table})")}
                if not set(columns).issubset(actual):
                    raise ValueError("这不是有效的 DayTrace 备份")
            if validation.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("备份的数据关联损坏")
            invalid = validation.execute("SELECT 1 FROM sessions WHERE seconds<=0 OR mode NOT IN ('foreground','active') LIMIT 1").fetchone()
            if invalid:
                raise ValueError("备份统计数据无效")
            for app in validation.execute("SELECT key,name,executable,category,excluded,icon FROM apps"):
                if not all(isinstance(app[index], str) for index in (0, 1, 2, 3, 5)) or not app[0] or app[3] not in CATEGORIES or app[4] not in (0, 1):
                    raise ValueError("备份应用信息无效")
            for session in validation.execute("SELECT day,start,end,seconds FROM sessions"):
                try:
                    day = date.fromisoformat(session[0])
                    start, end = datetime.fromisoformat(session[1]), datetime.fromisoformat(session[2])
                    seconds = float(session[3])
                    valid_end = end.date() == day or (end.date() == day + timedelta(days=1) and end.time() == time.min)
                    valid = start.date() == day and valid_end and end > start and math.isfinite(seconds) and seconds > 0
                except (ValueError, TypeError, OverflowError):
                    valid = False
                if not valid:
                    raise ValueError("备份时间段格式或日期无效")
            for diary in validation.execute("SELECT date,completed,mood,body,tags FROM diaries"):
                try:
                    date.fromisoformat(diary[0])
                    tags = json.loads(diary[4])
                    valid = all(isinstance(diary[index], str) for index in (1, 2, 3)) and isinstance(tags, list) and all(isinstance(tag, str) for tag in tags)
                except (ValueError, TypeError):
                    valid = False
                if not valid:
                    raise ValueError("备份日记格式无效")
            for setting in validation.execute("SELECT key,value FROM settings"):
                try:
                    value = json.loads(setting[1])
                except (ValueError, TypeError) as error:
                    raise ValueError("备份设置 JSON 格式无效") from error
                if not self._valid_setting(setting[0], value):
                    raise ValueError("备份设置无效：" + str(setting[0]))
        finally:
            validation.close()
        # 先验证，再通过单个事务导入。任何约束或磁盘错误都会回滚原数据。
        with self._lock:
            self._connection.execute("ATTACH DATABASE ? AS restore_source", (str(source),))
            try:
                with self._connection:
                    for table in ("sessions", "receipts", "diaries", "settings", "apps"):
                        self._connection.execute(f"DELETE FROM {table}")
                    for table in ("apps", "sessions", "receipts", "diaries", "settings"):
                        columns = ",".join(self._TABLE_COLUMNS[table])
                        self._connection.execute(f"INSERT INTO main.{table}({columns}) SELECT {columns} FROM restore_source.{table}")
            finally:
                self._connection.execute("DETACH DATABASE restore_source")

    @staticmethod
    def _valid_setting(key: str, value) -> bool:
        if key == "mode":
            return value in ("foreground", "active")
        if key == "idle_threshold_seconds":
            return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and 0 < value <= 86400
        if key == "poll_interval_seconds":
            return isinstance(value, (float, int)) and not isinstance(value, bool) and value in (1, 2)
        if key == "theme":
            return value in ("light", "dark", "system")
        if key in ("reminder_enabled", "autostart"):
            return isinstance(value, bool)
        if key == "reminder_time":
            return isinstance(value, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) is not None
        if key == "tags":
            return isinstance(value, list) and all(isinstance(tag, str) for tag in value)
        return isinstance(key, str)

    def delete_date(self, value: str | date) -> None:
        day = _day(value)
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM sessions WHERE day=?", (day,))
            self._connection.execute("DELETE FROM receipts WHERE day=?", (day,))
            self._connection.execute("DELETE FROM diaries WHERE date=?", (day,))

    def clear_history(self) -> None:
        with self._lock, self._connection:
            for table in ("sessions", "receipts", "diaries"):
                self._connection.execute(f"DELETE FROM {table}")

    def close(self) -> None:
        with self._lock:
            self._connection.close()
