import argparse
import ctypes
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
from datetime import datetime

from PySide6.QtCore import (QAbstractNativeEventFilter, QDate, QLocale, QLockFile, QMetaObject, Q_ARG, Q_RETURN_ARG, QObject, QThread,
                           QTimer, Qt, Signal)
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QSystemTrayIcon

from daytrace.core.repository import Repository
from daytrace.platform.windows import is_autostart, set_autostart
from daytrace.service import TrackingWorker
from daytrace.ui.main_window import MainWindow


def data_directory():
    """测试环境可单独指定数据目录，正常安装始终使用当前用户本地目录。"""
    override = os.environ.get("DAYTRACE_DATA_DIR")
    return Path(override) if override else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DayTrace"


def app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#D66F9B"))
    painter.drawRoundedRect(3, 3, 58, 58, 18, 18)
    painter.setPen(QColor("#FFFFFF"))
    pen = painter.pen()
    pen.setWidth(4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawArc(14, 14, 36, 36, 45 * 16, 290 * 16)
    painter.drawLine(32, 21, 32, 33)
    painter.drawLine(32, 33, 42, 38)
    painter.end()
    return QIcon(pixmap)


class Commands(QObject):
    pause = Signal(bool)
    configure = Signal(dict)
    session = Signal(bool)
    reset = Signal()


class NativeEvents(QAbstractNativeEventFilter):
    def __init__(self, commands):
        super().__init__()
        self.commands = commands
        self.locked = False
        self.suspended = False
        self.disconnected = False

    def nativeEventFilter(self, event_type, message):
        if sys.platform != "win32":
            return False, 0
        try:
            from ctypes import wintypes
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            changed = False
            if msg.message == 0x02B1:  # WM_WTSSESSION_CHANGE
                if msg.wParam in (2, 4):
                    self.disconnected, changed = True, True
                elif msg.wParam in (1, 3):
                    self.disconnected, changed = False, True
                elif msg.wParam in (6, 7):  # LOGOFF / LOCK
                    self.locked, changed = True, True
                elif msg.wParam in (5, 8):  # LOGON / UNLOCK
                    self.locked, changed = False, True
            elif msg.message == 0x0218:  # WM_POWERBROADCAST
                if msg.wParam == 4:  # PBT_APMSUSPEND
                    self.suspended, changed = True, True
                elif msg.wParam in (6, 7, 18):
                    self.suspended, changed = False, True
            if changed:
                self.commands.session.emit(not (self.locked or self.suspended or self.disconnected))
        except Exception:
            logging.exception("系统事件处理失败")
        return False, 0


class DayTraceApplication(QObject):
    def __init__(self, application, repository, hidden=False):
        super().__init__()
        self.application = application
        self.repository = repository
        self.commands = Commands()
        self.thread = QThread(self)
        self.thread.setObjectName("DayTraceTracking")
        self.worker = TrackingWorker(repository)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.thread.finished.connect(self.worker.deleteLater)
        self.commands.pause.connect(self.worker.set_paused)
        self.commands.configure.connect(self.worker.configure)
        self.commands.session.connect(self.worker.session_changed)
        self.commands.reset.connect(self.worker.reset)
        self.window = MainWindow(repository, {
            "pause": self.commands.pause.emit,
            "settings_changed": self.settings_changed,
            "export": self.export, "backup": self.backup, "restore": self.restore,
            "delete_date": self.delete_date, "clear_history": self.clear_history, "quit": self.quit,
        })
        self.window.setWindowIcon(app_icon())
        self.worker.status.connect(self.status_changed)
        self.worker.changed.connect(self.refresh_visible)
        self.paused = False
        self.quitting = False
        self.last_today = QDate.currentDate()
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.window.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        menu = QMenu()
        menu.addAction("打开主界面", self.show)
        self.total_action = menu.addAction("今日累计 · 0 分钟", lambda: self.show_page(0))
        menu.addSeparator()
        self.pause_action = menu.addAction("暂停统计", lambda: self.commands.pause.emit(not self.paused))
        menu.addAction("打开设置", lambda: self.show_page(5))
        menu.addSeparator()
        menu.addAction("完全退出", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        menu.aboutToShow.connect(self.update_total)
        if self.window.tray_available:
            self.tray.show()
        self.native_filter = NativeEvents(self.commands)
        application.installNativeEventFilter(self.native_filter)
        self.wts = None
        if sys.platform == "win32":
            self.wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
            self.wts.WTSRegisterSessionNotification.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            self.wts.WTSRegisterSessionNotification.restype = ctypes.c_int
            self.wts.WTSUnRegisterSessionNotification.argtypes = [ctypes.c_void_p]
            if not self.wts.WTSRegisterSessionNotification(int(self.window.winId()), 0):
                logging.warning("会话通知注册失败，继续使用安全桌面检测和时钟间隔防护")
        self.reminder = QTimer(self)
        self.reminder.setInterval(30000)
        self.reminder.timeout.connect(self.check_reminder)
        self.reminder.start()
        self.thread.start()
        if not hidden or not self.window.tray_available:
            self.show()

    def show(self):
        self.sync_day()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.window.refresh()

    def show_page(self, index):
        self.window.show_page(index)
        self.show()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show()

    def status_changed(self, text, paused):
        self.paused = paused
        self.pause_action.setText("恢复统计" if paused else "暂停统计")
        self.tray.setToolTip(f"DayTrace · {text}")
        self.window.set_tracking_status(text, paused)

    def update_total(self):
        value = self.repository.daily_summary(datetime.now().date().isoformat())["total"]
        minutes = int(value // 60)
        self.total_action.setText(f"今日累计 · {minutes // 60} 小时 {minutes % 60} 分钟")

    def refresh_visible(self):
        if self.window.isVisible():
            self.sync_day()
            self.window.refresh()

    def sync_day(self):
        today = QDate.currentDate()
        if today != self.last_today:
            if self.window.selected_date == self.last_today:
                self.window.select_date(today)
            self.last_today = today

    def settings_changed(self, options):
        if not self.save_barrier():
            raise RuntimeError("尚有记录未保存，设置未生效")
        previous_autostart = bool(self.repository.get_setting("autostart", False))
        if "autostart" in options and bool(options["autostart"]) != previous_autostart:
            try:
                set_autostart(bool(options["autostart"]))
            except Exception as error:
                raise RuntimeError(f"开机启动设置失败，已保留原设置：{error}") from error
        applied = QMetaObject.invokeMethod(self.worker, "configure", Qt.ConnectionType.BlockingQueuedConnection, Q_RETURN_ARG(bool), Q_ARG("QVariantMap", options))
        if not applied:
            raise RuntimeError("统计设置应用失败，请查看本地错误日志")
        for key, value in options.items():
            self.repository.set_setting(key, value)

    def save_barrier(self):
        if not self.window.flush_diary():
            QMessageBox.warning(self.window, "日记尚未保存", "请先处理日记保存失败；编辑内容仍保留在窗口中。")
            return False
        saved = QMetaObject.invokeMethod(self.worker, "barrier", Qt.ConnectionType.BlockingQueuedConnection, Q_RETURN_ARG(bool))
        if not saved:
            QMessageBox.warning(self.window, "统计尚未保存", "统计保存失败，操作已停止。请检查磁盘空间和本地错误日志后重试。")
        return bool(saved)

    def report_error(self, operation, error):
        logging.exception(operation)
        QMessageBox.warning(self.window, operation, str(error))

    def export(self, format):
        path, _ = QFileDialog.getSaveFileName(self.window, "导出全部历史", f"DayTrace.{format}", f"{format.upper()} (*.{format})")
        if path:
            try:
                if not self.save_barrier():
                    return
                self.repository.export(path, format=format)
                QMessageBox.information(self.window, "导出完成", f"已保存：{path}")
            except Exception as error:
                self.report_error("导出失败", error)

    def backup(self):
        path, _ = QFileDialog.getSaveFileName(self.window, "备份数据库", "DayTrace-backup.sqlite3", "SQLite 数据库 (*.sqlite3)")
        if path:
            try:
                if not self.save_barrier():
                    return
                self.repository.backup(path)
                QMessageBox.information(self.window, "备份完成", f"已保存：{path}")
            except Exception as error:
                self.report_error("备份失败", error)

    def restore(self):
        path, _ = QFileDialog.getOpenFileName(self.window, "选择 DayTrace 数据库备份", "", "SQLite 数据库 (*.sqlite3 *.db);;所有文件 (*)")
        if not path:
            return
        if QMessageBox.question(self.window, "恢复备份", "恢复会替换当前历史、日记和设置。将先保存恢复前备份，是否继续？") != QMessageBox.StandardButton.Yes:
            return
        try:
            if not self.save_barrier():
                return
            directory = self.repository.path.parent
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.repository.backup(directory / f"before-restore-{stamp}.sqlite3")
            self.repository.restore(path)
            self.repository.set_setting("autostart", is_autostart())
            options = {key: self.repository.get_setting(key, default) for key, default in (
                ("mode", "foreground"), ("idle_threshold_seconds", 300), ("poll_interval_seconds", 2))}
            self.commands.configure.emit(options)
            self.window.reload_after_restore()
            self.window.refresh()
            QMessageBox.information(self.window, "恢复完成", "数据已恢复。开机启动请在设置中重新确认；恢复前备份已保存在本地数据目录。")
        except Exception as error:
            self.report_error("恢复失败，当前数据保留", error)

    def delete_date(self, date):
        try:
            if not self.save_barrier():
                return
            self.repository.delete_date(date)
            self.window.invalidate_diary()
            self.window.refresh()
        except Exception as error:
            self.report_error("删除失败", error)

    def clear_history(self):
        try:
            if not self.save_barrier():
                return
            self.repository.clear_history()
            self.window.invalidate_diary()
            self.window.refresh()
        except Exception as error:
            self.report_error("清空失败", error)

    def check_reminder(self):
        if not self.repository.get_setting("reminder_enabled", False):
            return
        now = datetime.now()
        today = now.date().isoformat()
        when = self.repository.get_setting("reminder_time", "21:30")
        if now.strftime("%H:%M") >= when and self.repository.get_setting("reminder_last_date", "") != today:
            self.repository.set_setting("reminder_last_date", today)
            self.tray.showMessage("DayTrace · 今日回顾", "留两分钟，记下今天完成的事和心情。", QSystemTrayIcon.MessageIcon.Information, 10000)

    def quit(self):
        if self.quitting:
            return
        # 主窗口可能有未到防抖保存时间的日记，退出前先保存。
        if hasattr(self.window, "flush_diary"):
            self.window.flush_diary()
            if 3 in self.window.pages and self.window.pages[3].dirty:
                self.show_page(3)
                QMessageBox.warning(self.window, "日记尚未保存", "日记保存失败。内容已保留在编辑器，请复制备份或检查可用空间后重试退出。")
                return
        self.quitting = True
        self.reminder.stop()
        saved = QMetaObject.invokeMethod(self.worker, "stop", Qt.ConnectionType.BlockingQueuedConnection, Q_RETURN_ARG(bool))
        if not saved:
            self.quitting = False
            self.reminder.start()
            self.show()
            QMessageBox.warning(self.window, "退出前保存失败", "未保存的统计仍保留在内存，已暂停计时。请检查磁盘空间和本地日志后，再选择完全退出。")
            return
        self.thread.quit()
        self.thread.wait()
        if self.wts:
            self.wts.WTSUnRegisterSessionNotification(int(self.window.winId()))
        self.tray.hide()
        self.repository.close()
        self.application.quit()

    def finish_system_exit(self):
        """系统已经进入退出流程时仍结束线程，防止 Qt 析构正在运行的线程。"""
        if self.thread.isRunning():
            QMetaObject.invokeMethod(self.worker, "stop", Qt.ConnectionType.BlockingQueuedConnection, Q_RETURN_ARG(bool))
            self.thread.quit()
            self.thread.wait()
        if not self.quitting:
            self.quitting = True
            self.tray.hide()
            self.repository.close()


def main():
    parser = argparse.ArgumentParser(description="DayTrace 本地生活日志")
    parser.add_argument("--hidden", action="store_true", help="启动后隐藏到系统托盘")
    parser.add_argument("--smoke-seconds", type=int, default=0, help="测试用：指定秒数后正常退出")
    args = parser.parse_args()
    application = QApplication(sys.argv[:1])
    QLocale.setDefault(QLocale(QLocale.Language.Chinese, QLocale.Country.China))
    application.setApplicationName("DayTrace")
    application.setOrganizationName("DayTrace")
    application.setQuitOnLastWindowClosed(False)
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "daytrace.log", maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    # 本地 socket 与数据目录绑定；重复启动只打开现有实例，不产生重复统计。
    import hashlib
    name = "DayTrace-" + hashlib.sha256(str(directory.resolve()).casefold().encode()).hexdigest()[:24]
    socket = QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(400):
        socket.write(b"show")
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return 0
    instance_lock = QLockFile(str(directory / "instance.lock"))
    instance_lock.setStaleLockTime(0)
    if not instance_lock.tryLock(0):
        socket.connectToServer(name)
        if socket.waitForConnected(2000):
            socket.write(b"show")
            socket.waitForBytesWritten(500)
            return 0
        QMessageBox.warning(None, "DayTrace 已在运行", "另一个实例正在启动或退出，请稍后再打开。")
        return 0
    server = QLocalServer()
    if not server.listen(name):
        QLocalServer.removeServer(name)
        if not server.listen(name):
            QMessageBox.warning(None, "DayTrace 无法启动", "无法建立本地实例锁，请稍后重试。")
            return 1
    try:
        repository = Repository(directory / "daytrace.sqlite3")
    except Exception as error:
        QMessageBox.critical(None, "数据库无法打开", f"请保留原数据库，检查可用空间或恢复有效备份。\n{error}")
        return 1
    controller = DayTraceApplication(application, repository, args.hidden)
    def on_connection():
        while server.hasPendingConnections():
            client = server.nextPendingConnection()
            client.disconnectFromServer()
            client.deleteLater()
            controller.show()
    server.newConnection.connect(on_connection)
    if args.smoke_seconds:
        QTimer.singleShot(max(1, args.smoke_seconds) * 1000, controller.quit)
    application.aboutToQuit.connect(controller.finish_system_exit)
    return application.exec()
