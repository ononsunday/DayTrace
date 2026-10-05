"""计时放在工作线程，隐藏主窗口不会停止服务。"""
import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from daytrace.core.tracker import Tracker
from daytrace.platform.windows import WindowsDetector


class TrackingWorker(QObject):
    status = Signal(str, bool)
    changed = Signal()
    stopped = Signal()

    def __init__(self, repository):
        super().__init__()
        self.repository = repository
        self.detector = WindowsDetector()
        self.tracker = Tracker(repository)
        self.timer = None
        self.paused = False
        self.session_available = True
        self.options = {}
        self.last_status = None
        self.last_notify = 0.0

    @Slot()
    def start(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.configure({
            "mode": self.repository.get_setting("mode", "foreground"),
            "idle_threshold_seconds": self.repository.get_setting("idle_threshold_seconds", 300),
            "poll_interval_seconds": self.repository.get_setting("poll_interval_seconds", 2),
        })
        self.timer.start()
        self.tick()

    @Slot(dict, result=bool)
    def configure(self, options):
        try:
            self.options.update(options)
            mode = self.options.get("mode", "foreground")
            threshold = max(30, min(3600, int(self.options.get("idle_threshold_seconds", 300))))
            self.tracker.configure(mode=mode, idle_threshold=threshold)
            if self.timer:
                self.timer.setInterval(1000 if int(self.options.get("poll_interval_seconds", 2)) == 1 else 2000)
            return True
        except Exception:
            logging.exception("统计设置应用失败")
            self.status.emit("统计设置应用失败，请检查本地日志后重试", self.paused)
            return False

    @Slot(bool)
    def set_paused(self, value):
        # 切换暂停状态时只保存已经采样确认的时间，下一次重新建立起点。
        self.paused = value
        self.barrier()
        self.last_status = None
        self.tick()
        self.changed.emit()

    @Slot(bool)
    def session_changed(self, available):
        # 锁屏和电源事件即时切断会话，不能让休眠后的第一个间隔补记。
        self.session_available = available
        self.barrier()
        self.last_status = None
        self.tick()

    @Slot()
    def reset(self):
        self.barrier()
        self.last_status = None

    @Slot(result=bool)
    def barrier(self):
        """跨线程返回保存结果，删除和恢复不能在保存失败后继续。"""
        try:
            self.tracker.reset()
            return True
        except Exception:
            logging.exception("切断会话时保存失败，未保存批次保留等待重试")
            self.status.emit("保存失败 · 已停止本段计时，请检查本地日志", self.paused)
            return False

    @Slot()
    def tick(self):
        try:
            if self.paused:
                label = "统计已暂停"
            elif not self.session_available:
                label = "锁屏或休眠 · 暂停计时"
            else:
                sample = self.detector.sample()
                self.tracker.observe(sample)
                if not sample.available:
                    label = "锁屏或安全桌面 · 暂停计时"
                elif self.options.get("mode", "foreground") == "active" and (
                    sample.idle_seconds is None or sample.idle_seconds >= self.options.get("idle_threshold_seconds", 300)
                ):
                    label = "空闲中 · 暂停计时"
                elif sample.app is None:
                    label = "等待前台应用"
                elif self.repository.is_excluded(sample.app.key):
                    label = "前台应用已排除"
                else:
                    label = f"正在记录 · {sample.app.name}"
            state = (label, self.paused)
            if state != self.last_status:
                self.status.emit(*state)
                self.last_status = state
            if time.monotonic() - self.last_notify >= 30:
                self.changed.emit()
                self.last_notify = time.monotonic()
        except Exception:
            logging.exception("统计采样或保存失败")
            self.status.emit("统计暂时失败 · 将自动重试，请查看本地日志", self.paused)

    @Slot(result=bool)
    def stop(self):
        if self.timer:
            self.timer.stop()
        if not self.barrier():
            self.paused = True
            if self.timer:
                self.timer.start()
            self.status.emit("保存失败 · 保留记录并暂停统计，请检查后重试退出", True)
            return False
        self.stopped.emit()
        return True
