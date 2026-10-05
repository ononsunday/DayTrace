"""只将已确认的相邻前台采样区间计入统计，时间来源为单调时钟。"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import timedelta
import threading
import uuid

from .models import Observation, Segment


class Tracker:
    def __init__(self, repository, mode: str = "foreground", idle_threshold: float = 300, max_gap: float = 6, flush_interval: float = 30):
        self.repository = repository
        self.mode = "foreground"
        self.idle_threshold = 300.0
        self.max_gap = float(max_gap)
        self.flush_interval = float(flush_interval)
        if not math.isfinite(self.max_gap) or self.max_gap <= 0 or not math.isfinite(self.flush_interval) or self.flush_interval <= 0:
            raise ValueError("检测间隔上限和保存间隔必须大于零")
        self._previous: Observation | None = None
        self._pending: list[Segment] = []
        self._frozen_count = 0
        self._last_flush: float | None = None
        self._lock = threading.RLock()
        self._status = "等待检测"
        self.configure(mode, idle_threshold)

    @property
    def status(self) -> str:
        return self._status

    def configure(self, mode: str, idle_threshold: float) -> None:
        if mode not in ("foreground", "active"):
            raise ValueError("统计模式必须为 foreground 或 active")
        if not math.isfinite(float(idle_threshold)) or float(idle_threshold) <= 0:
            raise ValueError("空闲阈值必须大于零")
        with self._lock:
            try:
                self.reset()
            finally:
                # 旧批次带着原模式保留；保存失败也不能让新采样使用旧设置。
                self.mode = mode
                self.idle_threshold = float(idle_threshold)

    def observe(self, current: Observation) -> None:
        with self._lock:
            previous = self._previous
            # 重复或乱序采样不能改变基准，否则后续采样会重复计算。
            if previous is not None and current.monotonic <= previous.monotonic:
                return
            if not math.isfinite(current.monotonic):
                self.reset()
                return
            self._previous = current
            if self._last_flush is None:
                self._last_flush = current.monotonic
            self._status = self._describe(current)
            if previous is not None:
                elapsed = current.monotonic - previous.monotonic
                wall_elapsed = (current.wall - previous.wall).total_seconds()
                # 休眠/调试暂停/系统时间跳变的区间无法确定归属，整段舍弃。
                reliable = 0 < elapsed <= self.max_gap and wall_elapsed > 0 and abs(wall_elapsed - elapsed) <= 0.5
                if reliable and previous.available and current.available and previous.app is not None:
                    if not self.repository.is_excluded(previous.app.key):
                        start_offset, end_offset = self._effective_interval(previous, current, elapsed, wall_elapsed)
                        if end_offset > start_offset:
                            # 秒数由单调时钟决定；显示边界按墙钟跨度同比映射。
                            start = previous.wall + timedelta(seconds=start_offset * wall_elapsed / elapsed)
                            end = current.wall if end_offset == elapsed else previous.wall + timedelta(seconds=end_offset * wall_elapsed / elapsed)
                            self._queue(Segment(previous.app, start, end, end_offset - start_offset, self.mode))
                changed = previous.app != current.app or previous.available != current.available
                if changed or current.monotonic - self._last_flush >= self.flush_interval:
                    self.flush()
                    self._last_flush = current.monotonic

    def _effective_interval(self, previous: Observation, current: Observation, elapsed: float, wall_elapsed: float) -> tuple[float, float]:
        if self.mode == "foreground":
            return 0.0, elapsed
        if previous.idle_seconds is None or current.idle_seconds is None:
            return 0.0, 0.0
        if not math.isfinite(previous.idle_seconds) or not math.isfinite(current.idle_seconds):
            return 0.0, 0.0
        before = max(0.0, previous.idle_seconds)
        after = max(0.0, current.idle_seconds)
        threshold = self.idle_threshold
        # 没有新输入时，精确统计至阈值边界；超过阈值的尾段不计时。
        if abs(after - (before + elapsed)) <= 0.1:
            return 0.0, min(elapsed, max(0.0, threshold - before))
        if after > elapsed + 0.1:
            # 空闲计时器发生无法解释的跳变，不能据此假设用户已恢复操作。
            return 0.0, 0.0
        # 输入发生于当前采样前 after 秒。空闲恢复时只统计输入后的已知区间。
        input_offset = max(0.0, min(elapsed, elapsed - after))
        if before >= threshold:
            return input_offset, min(elapsed, input_offset + threshold)
        if before + input_offset <= threshold:
            return 0.0, min(elapsed, input_offset + threshold)
        # 同一采样内先进入空闲再恢复，空闲前后的有效部分需拆开。
        valid_before = max(0.0, min(elapsed, threshold - before))
        if valid_before > 0 and previous.app is not None:
            end = previous.wall + timedelta(seconds=valid_before * wall_elapsed / elapsed)
            self._queue(Segment(previous.app, previous.wall, end, valid_before, self.mode))
        return input_offset, min(elapsed, input_offset + threshold)

    def _queue(self, segment: Segment) -> None:
        if not segment.ingestion_id:
            # 新事件分配 token；回拨后相同墙钟时间仍是不同的实际使用区间。
            segment = replace(segment, ingestion_id=uuid.uuid4().hex)
        if len(self._pending) > self._frozen_count and self._pending[-1].app == segment.app and self._pending[-1].end == segment.start and self._pending[-1].mode == segment.mode:
            previous = self._pending[-1]
            self._pending[-1] = Segment(previous.app, previous.start, segment.end, previous.seconds + segment.seconds, previous.mode, previous.ingestion_id)
        else:
            if len(self._pending) >= 4096:
                self.flush()
            self._pending.append(segment)

    def flush(self) -> None:
        with self._lock:
            if self._pending:
                # 成功落库后才清空；写入错误时可重试同一批，不丢失已确认区间。
                try:
                    self.repository.append_segments(self._pending)
                except Exception:
                    # 即使提交成功后的调用层异常，原批次也不可再被合并改写。
                    self._frozen_count = len(self._pending)
                    raise
                self._pending.clear()
                self._frozen_count = 0

    def reset(self) -> None:
        with self._lock:
            try:
                self.flush()
            finally:
                # 锁屏/暂停边界必须切断，即使保存失败也不在恢复后补记间隙。
                self._previous = None
                self._last_flush = None
                self._status = "等待检测"

    def _describe(self, observation: Observation) -> str:
        if not observation.available:
            return "已暂停（锁屏或不可检测）"
        if observation.app is None:
            return "等待前台应用"
        if self.repository.is_excluded(observation.app.key):
            return "当前应用已排除"
        if self.mode == "active" and (observation.idle_seconds is None or observation.idle_seconds >= self.idle_threshold):
            return "空闲中"
        return "正在统计：" + observation.app.name
