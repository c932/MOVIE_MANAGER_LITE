"""Qt 刮削任务调度：后台 I/O、代际隔离、协作取消和线程所有权。"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage, QImageReader


@dataclass
class TaskContext:
    cancelled: threading.Event = field(default_factory=threading.Event)
    report: Callable[[object], None] = lambda value: None

    def check_cancelled(self) -> bool:
        return self.cancelled.is_set()

    def checkpoint(self) -> None:
        if self.check_cancelled():
            raise InterruptedError("任务已取消")


class _TaskThread(QThread):
    succeeded = pyqtSignal(str, int, object)
    failed = pyqtSignal(str, int, str)
    progress = pyqtSignal(str, int, object)

    def __init__(self, channel: str, generation: int, function: Callable, parent: QObject):
        super().__init__(parent)
        self.channel, self.generation = channel, generation
        self.function = function
        self.context = TaskContext(report=self._report)

    def _report(self, value: object) -> None:
        self.progress.emit(self.channel, self.generation, value)

    def run(self) -> None:
        try:
            if self.channel not in {"write", "settings-save", "queue-load", "queue-save"}:
                self.context.checkpoint()
            value = self.function(self.context)
            # 已开始的写盘即使取消也必须汇报已完成结果。
            self.succeeded.emit(self.channel, self.generation, value)
        except InterruptedError:
            pass
        except Exception as exc:
            self.failed.emit(self.channel, self.generation, str(exc))


class TaskRunner(QObject):
    """所有回调经本 QObject 的主线程槽转发；不 terminate、不阻塞 wait。"""

    result = pyqtSignal(str, int, object)
    error = pyqtSignal(str, int, str)
    progress = pyqtSignal(str, int, object)
    idle = pyqtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._threads: set[_TaskThread] = set()
        self._generations: dict[str, int] = {}

    @property
    def busy(self) -> bool:
        return bool(self._threads)

    def invalidate(self, channel: str) -> int:
        generation = self._generations.get(channel, 0) + 1
        self._generations[channel] = generation
        for thread in self._threads:
            if thread.channel == channel:
                thread.context.cancelled.set()
        return generation

    def start(self, channel: str, function: Callable[[TaskContext], object]) -> int:
        generation = self.invalidate(channel)
        thread = _TaskThread(channel, generation, function, self)
        self._threads.add(thread)
        thread.succeeded.connect(self._result)
        thread.failed.connect(self._error)
        thread.progress.connect(self._progress)
        thread.finished.connect(self._finished)
        thread.start()
        return generation

    def cancel(self) -> None:
        for channel in tuple(self._generations):
            if channel not in {"write", "settings-save", "queue-load", "queue-save"}:
                self.invalidate(channel)
        for thread in self._threads:
            thread.context.cancelled.set()

    @pyqtSlot(str, int, object)
    def _result(self, channel: str, generation: int, value: object) -> None:
        if self._generations.get(channel) == generation:
            self.result.emit(channel, generation, value)

    @pyqtSlot(str, int, str)
    def _error(self, channel: str, generation: int, message: str) -> None:
        if self._generations.get(channel) == generation:
            self.error.emit(channel, generation, message)

    @pyqtSlot(str, int, object)
    def _progress(self, channel: str, generation: int, value: object) -> None:
        if self._generations.get(channel) == generation:
            self.progress.emit(channel, generation, value)

    @pyqtSlot()
    def _finished(self) -> None:
        thread = self.sender()
        self._threads.discard(thread)
        thread.deleteLater()
        if not self._threads:
            self.idle.emit()


def download_preview(url: str, settings: object, context: TaskContext) -> QImage:
    """仅后台调用；有界下载并在 QImageReader 解码前限制像素数。"""
    from scraper.scrape_http import HttpClient
    context.checkpoint()
    payload = HttpClient(settings).get_bytes(url, max_bytes=8 * 1024 * 1024)
    context.checkpoint()
    buffer = QBuffer()
    buffer.setData(QByteArray(bytes(payload)))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 25_000_000:
        raise ValueError("缩略图尺寸无效或过大")
    image = reader.read()
    if image.isNull():
        raise ValueError("缩略图无法解码")
    return image.scaled(240, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def safe_message(message: str, settings: object = None) -> str:
    """异常可展示，但不回显输入的凭据。"""
    for field_name in ("tmdb_api_key", "tmdb_token", "omdb_api_key"):
        secret = getattr(settings, field_name, "")
        if secret:
            message = message.replace(secret, "***")
    return message
