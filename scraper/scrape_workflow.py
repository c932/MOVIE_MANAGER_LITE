"""
刮削工作流引擎 - 基于 douban-cli

完整工作流：
1. 使用 douban-cli 搜索电影并注入豆瓣评分到 NFO 文件
2. 通知主程序刷新媒体库

此模块完全独立，不依赖现有电影墙任何核心代码。
"""
import os
import logging
import time
import random
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta

from PyQt6.QtCore import QThread, pyqtSignal, QObject

logger = logging.getLogger(__name__)


class WorkflowStep(Enum):
    """工作流步骤"""
    DOUBAN_INJECT = "douban_inject"
    REFRESH_LIBRARY = "refresh_library"


class StepStatus(Enum):
    """步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ScrapeConfig:
    """刮削配置 - 仅 douban-cli"""
    # 豆瓣注入选项
    douban_skip_existing: bool = True   # 跳过已有豆瓣评分的
    douban_skip_failed: bool = True     # 跳过已记录的失败电影
    douban_recursive: bool = True       # 递归扫描
    douban_inject_new_only: bool = False  # 仅注入新扫描的电影
    douban_new_days: int = 7            # 新电影判断天数（0=处理所有）
    douban_delay: float = 2.0           # 请求延迟（秒）
    douban_timeout: int = 1800          # 总超时（秒）


@dataclass
class StepResult:
    """单步结果"""
    step: WorkflowStep
    status: StepStatus = StepStatus.PENDING
    message: str = ""
    details: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class FailedMovie:
    """匹配失败的电影信息"""
    nfo_file: str
    title: str
    year: str
    original_title: str = ""


@dataclass
class WorkflowResult:
    """整体工作流结果"""
    steps: List[StepResult] = field(default_factory=list)
    total_elapsed: float = 0.0
    failed_movies: List[FailedMovie] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(s.status in (StepStatus.SUCCESS, StepStatus.SKIPPED)
                   for s in self.steps)


class ScrapeWorker(QThread):
    """
    刮削工作流线程（douban-cli 专用）

    信号:
        step_started(str)       - 步骤开始，参数为步骤描述
        step_progress(str)      - 步骤进度日志
        step_finished(str, bool) - 步骤完成，参数为(描述, 是否成功)
        workflow_finished(object) - 整体完成，参数为 WorkflowResult
    """
    step_started = pyqtSignal(str)
    step_progress = pyqtSignal(str)
    step_finished = pyqtSignal(str, bool)
    workflow_finished = pyqtSignal(object)

    def __init__(self, config: ScrapeConfig, movie_paths: List[str],
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self.config = config
        self.movie_paths = movie_paths
        self._cancelled = False

    def cancel(self):
        """取消工作流"""
        self._cancelled = True

    def run(self):
        """执行完整工作流"""
        result = WorkflowResult()
        workflow_start = time.time()

        try:
            # ===== Step 1: 豆瓣评分注入 =====
            if True:  # 始终执行
                douban_result, failed_movies = self._run_douban_scrape()
                result.steps.append(douban_result)
                result.failed_movies = failed_movies

            if self._cancelled:
                self._emit_cancelled(result, workflow_start)
                return

            # ===== Step 2: 刷新信号 =====
            refresh_result = StepResult(
                step=WorkflowStep.REFRESH_LIBRARY,
                status=StepStatus.SUCCESS,
                message="媒体库刷新信号已发送"
            )
            result.steps.append(refresh_result)

        except Exception as e:
            logger.exception("工作流异常")
            self.step_progress.emit(f"❌ 工作流异常: {e}")

        result.total_elapsed = time.time() - workflow_start
        self.workflow_finished.emit(result)

    def _emit_cancelled(self, result: WorkflowResult, start_time: float):
        """发出取消信号"""
        result.total_elapsed = time.time() - start_time
        self.step_progress.emit("⚠️ 工作流已取消")
        self.workflow_finished.emit(result)

    # ─────────────────── 豆瓣评分注入 ───────────────────

    def _run_douban_scrape(self) -> tuple:
        """
        使用 douban-cli 搜索电影并注入豆瓣评分到 NFO 文件。

        Returns:
            (StepResult, List[FailedMovie])
        """
        from scraper.douban_cli import (
            search_movie, get_movie_detail, inject_douban_to_nfo, read_nfo_movie_info
        )
        from utils.failed_movies_manager import FailedMoviesManager

        step_result = StepResult(step=WorkflowStep.DOUBAN_INJECT)
        step_start = time.time()
        failed_movies = []

        self.step_started.emit("🟢 步骤 1/2：豆瓣评分注入")

        stats = {
            'total': 0, 'success': 0, 'failed': 0,
            'skipped': 0, 'skipped_failed': 0, 'skipped_old': 0
        }

        # 初始化失败记录管理
        failed_manager = FailedMoviesManager()
        if self.config.douban_skip_failed:
            self.step_progress.emit(f"  已启用失败记录过滤，当前失败记录: {failed_manager.get_failed_count()} 个")

        try:
            # 收集所有 NFO 文件
            all_nfo_files = []
            for movie_path in self.movie_paths:
                if not os.path.exists(movie_path):
                    self.step_progress.emit(f"  ⚠️ 路径不存在: {movie_path}")
                    continue
                nfo_files = self._find_nfo_files(movie_path, self.config.douban_recursive)
                all_nfo_files.extend(nfo_files)

            # 过滤 NFO 文件
            filtered_nfo_files = []
            cutoff_time = None

            if self.config.douban_inject_new_only and self.config.douban_new_days > 0:
                cutoff_time = datetime.now() - timedelta(days=self.config.douban_new_days)
                self.step_progress.emit(
                    f"  仅处理最近 {self.config.douban_new_days} 天修改的 NFO"
                    f"（{cutoff_time.strftime('%Y-%m-%d %H:%M:%S')} 之后）"
                )

            for nfo_file in all_nfo_files:
                if self.config.douban_skip_failed and failed_manager.is_failed(nfo_file):
                    stats['skipped_failed'] += 1
                    continue

                if cutoff_time:
                    try:
                        mtime = datetime.fromtimestamp(os.path.getmtime(nfo_file))
                        if mtime < cutoff_time:
                            stats['skipped_old'] += 1
                            continue
                    except Exception:
                        pass

                filtered_nfo_files.append(nfo_file)

            total_found = len(all_nfo_files)
            total = len(filtered_nfo_files)
            stats['total'] = total

            self.step_progress.emit(f"找到 {total_found} 个 NFO 文件")
            if stats['skipped_failed'] > 0:
                self.step_progress.emit(f"  跳过 {stats['skipped_failed']} 个已失败的电影")
            if stats['skipped_old'] > 0:
                self.step_progress.emit(
                    f"  跳过 {stats['skipped_old']} 个旧电影"
                    f"（修改时间早于 {self.config.douban_new_days} 天）"
                )
            self.step_progress.emit(f"实际处理 {total} 个 NFO 文件")

            if total == 0:
                step_result.status = StepStatus.SUCCESS
                step_result.message = "没有找到需要处理的 NFO 文件"
                return (step_result, failed_movies)

            for idx, nfo_file in enumerate(filtered_nfo_files, 1):
                if self._cancelled:
                    self.step_progress.emit("  ⚠️ 用户取消")
                    break

                try:
                    info = read_nfo_movie_info(nfo_file)
                    if not info:
                        stats['failed'] += 1
                        continue

                    title = info['title']
                    year = info['year']
                    original_title = info['original_title']

                    if not title:
                        stats['failed'] += 1
                        continue

                    # 跳过已有豆瓣评分的
                    if self.config.douban_skip_existing and info['has_douban']:
                        stats['skipped'] += 1
                        continue

                    self.step_progress.emit(
                        f"  [{idx}/{total}] 处理: {title} ({year or '?'})"
                    )

                    # === 多级搜索策略 ===
                    detail = None
                    matched_id = None
                    search_attempts = []

                    def try_search(keyword: str, label: str) -> Optional[dict]:
                        """尝试搜索并返回结果"""
                        result = search_movie(keyword, year)
                        search_attempts.append((label, keyword))
                        return result

                    # 策略1: 中文名
                    search_result = try_search(title, '中文名')

                    # 策略2: 英文原名
                    if not search_result and original_title and original_title != title:
                        self.step_progress.emit(f"    ⚠️ 中文名未找到，尝试英文原名: {original_title}")
                        search_result = try_search(original_title, '英文原名')

                    # 策略3: 简化标题（去掉冒号后的副标题）
                    if not search_result and (':' in title or '：' in title):
                        simple_title = title.replace('：', ':').split(':')[0].strip()
                        if simple_title and simple_title != title:
                            self.step_progress.emit(f"    ⚠️ 尝试简化标题: {simple_title}")
                            search_result = try_search(simple_title, '简化标题')

                    # 策略4: 简化英文标题
                    if not search_result and original_title and (':' in original_title or '：' in original_title):
                        simple_original = original_title.replace('：', ':').split(':')[0].strip()
                        if simple_original and simple_original != original_title:
                            self.step_progress.emit(f"    ⚠️ 尝试简化英文标题: {simple_original}")
                            search_result = try_search(simple_original, '简化英文标题')

                    if not search_result:
                        attempts_str = ', '.join([f"{k}({v})" for k, v in search_attempts])
                        self.step_progress.emit(f"    ✗ 未找到豆瓣结果 (已尝试: {attempts_str})")
                        stats['failed'] += 1

                        failed_movie = FailedMovie(
                            nfo_file=nfo_file,
                            title=title,
                            year=year or "",
                            original_title=original_title or ""
                        )
                        failed_movies.append(failed_movie)

                        if self.config.douban_skip_failed:
                            failed_manager.add_failed(nfo_file, title, year or "")

                        time.sleep(self.config.douban_delay)
                        continue

                    matched_id = search_result['id']
                    matched_title = search_result.get('title', '未知')
                    matched_year = search_result.get('year', '')
                    year_info = f" ({matched_year})" if matched_year else ""

                    if len(search_attempts) > 1 or (search_attempts and search_attempts[0][0] != '中文名'):
                        strategy = search_attempts[-1][0]
                        self.step_progress.emit(f"    ✓ 通过{strategy}找到: {matched_title}{year_info}")
                    elif matched_year and matched_year != year:
                        self.step_progress.emit(f"    ✓ 匹配: {matched_title}{year_info}")

                    # === 获取详情 ===
                    delay = self.config.douban_delay + random.uniform(-0.3, 0.5)
                    time.sleep(max(0.5, delay))

                    detail = get_movie_detail(matched_id)
                    if not detail:
                        self.step_progress.emit(f"    ✗ 获取详情失败")
                        stats['failed'] += 1
                        continue

                    # === 注入 NFO ===
                    if inject_douban_to_nfo(nfo_file, matched_id, detail):
                        rating_str = detail.get('rating', '?')
                        self.step_progress.emit(
                            f"    ✓ {rating_str}/10 → {os.path.basename(nfo_file)}"
                        )
                        stats['success'] += 1

                        if failed_manager.is_failed(nfo_file):
                            failed_manager.remove_failed(nfo_file)
                    else:
                        stats['failed'] += 1

                    delay = self.config.douban_delay + random.uniform(-0.3, 0.5)
                    time.sleep(max(0.5, delay))

                except Exception as e:
                    self.step_progress.emit(f"  [{idx}/{total}] 异常: {e}")
                    stats['failed'] += 1

        except Exception as e:
            step_result.status = StepStatus.FAILED
            step_result.message = f"豆瓣注入异常: {e}"
            logger.exception("豆瓣注入异常")

        # 构建摘要
        summary_parts = [
            f"总计 {stats['total']}",
            f"成功 {stats['success']}",
            f"失败 {stats['failed']}"
        ]
        if stats['skipped'] > 0:
            summary_parts.append(f"跳过 {stats['skipped']}")
        if stats['skipped_failed'] > 0:
            summary_parts.append(f"跳过失败 {stats['skipped_failed']}")
        if stats['skipped_old'] > 0:
            summary_parts.append(f"跳过旧 {stats['skipped_old']}")

        summary = " | ".join(summary_parts)
        self.step_progress.emit(f"  📊 {summary}")

        if step_result.status != StepStatus.FAILED:
            step_result.status = StepStatus.SUCCESS
            step_result.message = f"豆瓣注入完成 - {summary}"
        step_result.details = summary
        step_result.elapsed_seconds = time.time() - step_start

        self.step_progress.emit(
            f"{'✅' if step_result.status == StepStatus.SUCCESS else '❌'} "
            f"{step_result.message} (耗时 {step_result.elapsed_seconds:.1f}秒)"
        )
        self.step_finished.emit("豆瓣注入", step_result.status == StepStatus.SUCCESS)
        return (step_result, failed_movies)

    def _find_nfo_files(self, directory: str, recursive: bool) -> List[str]:
        """查找目录中的 NFO 文件"""
        nfo_files = []
        try:
            if recursive:
                for root, dirs, files in os.walk(directory):
                    for f in files:
                        if f.lower().endswith('.nfo'):
                            nfo_files.append(os.path.join(root, f))
            else:
                for f in os.listdir(directory):
                    if f.lower().endswith('.nfo'):
                        nfo_files.append(os.path.join(directory, f))
        except PermissionError:
            self.step_progress.emit(f"  ⚠️ 权限不足: {directory}")
        except Exception as e:
            self.step_progress.emit(f"  ⚠️ 扫描异常: {e}")
        return nfo_files
