from dataclasses import dataclass
from datetime import datetime

CATEGORIES = ("学习与编程", "游戏娱乐", "社交聊天", "视频与音乐", "工作办公", "系统工具", "其他")

@dataclass(frozen=True)
class AppIdentity:
    key: str
    name: str
    executable: str = ""

@dataclass(frozen=True)
class Observation:
    monotonic: float
    wall: datetime
    app: AppIdentity | None
    idle_seconds: float | None = 0.0
    available: bool = True

@dataclass(frozen=True)
class Segment:
    app: AppIdentity
    start: datetime
    end: datetime
    seconds: float
    mode: str = "foreground"
    ingestion_id: str = ""
