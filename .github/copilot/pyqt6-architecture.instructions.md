---
applyTo: "**/*.py"
---

# PyQt6 应用架构 — 可复用模式

本文档总结在实际 PyQt6 桌面应用（本地电影墙）中验证过的架构模式，供同类项目参考。

---

## 1. QThread Worker 标准模式

### 模板

```python
from PyQt6.QtCore import QThread, pyqtSignal

class XxxWorker(QThread):
    progress  = pyqtSignal(int, str)   # (current, message)
    finished  = pyqtSignal(object)     # 结果对象，None 表示无返回值

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self._data     = data
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        for i, item in enumerate(self._data):
            if self._cancelled:
                break
            # ... 处理 item ...
            self.progress.emit(i + 1, f"处理 {item}")
        self.finished.emit(result)
```

### 关键规则

- **子线程严禁直接操作任何 UI 控件**，所有 UI 更新通过 signal 传回主线程。
- 取消用 `self._cancelled = True` 标志位，**不要调 `terminate()`**（会导致资源泄漏）。
- `closeEvent` 里必须：`worker.cancel(); worker.wait()`，防止窗口关闭后子线程继续访问已销毁对象。
- Worker 持有数据的引用时，注意线程安全：传入时复制一份（`list(data)`）。

### 注册与清理

```python
# 启动
self._worker = XxxWorker(data, parent=self)
self._worker.progress.connect(self._on_progress)
self._worker.finished.connect(self._on_finished)
self._worker.start()

# 窗口关闭
def closeEvent(self, event):
    if self._worker and self._worker.isRunning():
        self._worker.cancel()
        self._worker.wait()
    super().closeEvent(event)
```

---

## 2. Widget → Signal → MainWindow 解耦模式

### 原则

子 Widget（卡片、面板等）**只发信号，不持有 MainWindow 引用**；所有业务逻辑集中在 MainWindow。

```python
# movie_card.py — 只声明信号和基本交互
class MovieCard(QWidget):
    clicked       = pyqtSignal(Movie)
    right_clicked = pyqtSignal(Movie, object)  # object = QPoint

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(self._movie, event.globalPosition().toPoint())
        else:
            self.clicked.emit(self._movie)

# main_window.py — 统一处理业务
card.clicked.connect(self._on_card_clicked)
card.right_clicked.connect(self._on_card_right_clicked)

def _on_card_right_clicked(self, movie: Movie, pos):
    menu = QMenu(self)
    menu.addAction("播放", lambda: self._play(movie))
    menu.addAction("删除", lambda: self._delete(movie))
    menu.exec(pos)
```

### 好处

- Widget 可独立测试，无需 MainWindow 实例。
- 同一个 Widget 类型可以被不同的 parent 复用，signal 连接不同的 slot。

---

## 3. 增量刷新 + Diff 统计模式

适用于文件库类应用（扫描 NFO、扫描音乐/照片等）。

```python
def refresh_library(self):
    # 刷新前：保存快照
    self._old_movies = {m.nfo_path: m for m in self.movies}

    # 启动扫描（不清空缓存）
    self._scanner.start()

def on_movie_found(self, movie: Movie):
    # 保留旧版本的用户数据（观看时间、added_time 等）
    old = self._old_movies.get(movie.nfo_path)
    if old:
        movie.added_time = old.added_time

def on_scan_completed(self, new_movies: list):
    new_paths = {m.nfo_path for m in new_movies}
    old_paths = set(self._old_movies.keys())

    added   = new_paths - old_paths
    removed = old_paths - new_paths
    unchanged = old_paths & new_paths

    # 显示 diff 摘要
    msg = f"新增 {len(added)} 部，移除 {len(removed)} 部，共 {len(new_movies)} 部"
    self.status_bar.showMessage(msg)
```

### 关键点

- 扫描前保存 `{nfo_path: Movie}` 快照，扫描后对比路径集合做 set 运算。
- 不清空 poster 缓存，只失效已删除的条目（`PosterCacheManager.invalidate_cache_for_path`）。
- `added_time`、观看记录、收藏等用户数据在 `on_movie_found` 里从旧快照迁移，保证增量升级不丢数据。

---

## 4. 两级海报缓存模式

```
请求海报
  ├─ L1: ImageCache (内存 LRU, maxsize=200)   命中 → 直接返回 QPixmap
  └─ L2: PosterCacheManager (磁盘 JSON 索引 + 文件)
           命中 → 读文件 → 存 L1 → 返回
           未命中 → 网络/本地加载 → 存磁盘 → 存 L1 → 返回
```

**单条失效**（删除/更新单部电影时，不清空全部缓存）：

```python
# image_loader.py
class ImageCache:
    def remove(self, path: str) -> None:
        self._cache.pop(path, None)

# poster_cache_manager.py
def invalidate_cache_for_path(self, image_path: str) -> None:
    key = self._make_key(image_path)
    cache_file = self._cache_dir / key
    if cache_file.exists():
        cache_file.unlink()
    self._index.pop(key, None)
    self._flush_index()
    image_cache.remove(image_path)  # 同时清 L1
```

**后台预热**（启动扫描后，在后台线程提前加载常用尺寸）：

```python
class PosterPrimer(QThread):
    def run(self):
        for movie in self._movies:
            if self._cancelled: break
            for size in [(160, 240), (280, 420)]:  # wall + detail
                poster_cache.get_or_load(movie.poster_path, *size)
```

---

## 5. frozen/dev 路径分离

打包后资源目录（只读）和用户数据目录必须分开：

```python
import sys, os
from pathlib import Path

if getattr(sys, 'frozen', False):
    # PyInstaller 打包后
    RESOURCE_DIR = Path(sys._MEIPASS)           # 只读：QSS、logo 等打包资源
    DATA_DIR = Path(os.environ["APPDATA"]) / "MyApp" / "data"  # 用户数据
else:
    # 源码开发环境
    RESOURCE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = RESOURCE_DIR / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)
```

**常见错误**：打包后把 data 目录放在 exe 同级（`sys.executable.parent`），安装到 `Program Files` 后会因权限报 `PermissionError: [WinError 5]`。必须用 `%APPDATA%`。

---

## 6. QSS 动态加载

```python
def load_stylesheet(app: QApplication):
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent

    qss = base / "styles" / "style.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))
```

spec 里需把 `styles` 目录加入 `datas`：
```python
datas=[("styles", "styles"), ("logo", "logo")]
```
