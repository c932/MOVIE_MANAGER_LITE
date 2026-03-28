"""
刮削工作流引擎 - 独立模块

完整工作流：
1. 调用 TinyMediaManager CLI 刮削电影元数据
2. 调用 TMM_DOUBAN 注入豆瓣评分和链接
3. 通知主程序刷新媒体库

此模块完全独立，不依赖现有电影墙任何核心代码。
"""
import os
import sys
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta

from PyQt6.QtCore import QThread, pyqtSignal, QObject
from utils.app_paths import resolve_data_file

logger = logging.getLogger(__name__)


class WorkflowStep(Enum):
    """工作流步骤"""
    TMM_SCRAPE = "tmm_scrape"
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
    """刮削配置"""
    # TinyMediaManager 路径
    tmm_path: str = r"D:\Program Files\tinyMediaManager"
    tmm_cmd_exe: str = "tinyMediaManagerCMD.exe"

    # TMM_DOUBAN 路径
    douban_tool_path: str = r"E:\My Code\TMM_DOUBAN"
    douban_script: str = "douban_rating_injector_unified.py"

    # 工作流步骤启用标志
    enable_tmm_step: bool = True       # 启用 TMM 刮削步骤
    enable_douban_step: bool = True    # 启用豆瓣注入步骤

    # TMM 刮削选项
    tmm_update_all: bool = True        # -u 扫描所有数据源
    tmm_scrape_new: bool = True        # -n 刮削新发现的电影
    tmm_scrape_unscraped: bool = False  # --scrapeUnscraped 刮削所有未刮削的
    tmm_rename: bool = False           # -r 重命名

    # 豆瓣注入选项
    douban_mode: str = "normal"         # "normal" 或 "selenium"
    douban_skip_existing: bool = True   # 跳过已有豆瓣评分的
    douban_inject_new_only: bool = False # 仅注入新扫描的电影（通过 NFO 修改时间判断）
    douban_new_days: int = 7            # 新电影判断天数（0=处理所有）
    douban_skip_failed: bool = True     # 跳过已记录的失败电影
    douban_recursive: bool = True       # 递归扫描
    douban_delay: float = 2.5           # 请求延迟（秒）
    douban_cookie: str = ""             # 豆瓣 Cookie（普通模式可选）
    
    # Selenium 模式选项
    selenium_headless: bool = True      # 无头模式
    selenium_enable_login: bool = False # 启用手动登录
    selenium_cookie_file: str = str(resolve_data_file("douban_cookies.pkl"))  # Cookie 文件路径

    # 超时设置（秒）
    tmm_timeout: int = 600              # TMM 刮削超时 10 分钟
    douban_timeout: int = 1800          # 豆瓣注入超时 30 分钟


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
    failed_movies: List[FailedMovie] = field(default_factory=list)  # 匹配失败的电影列表

    @property
    def success(self) -> bool:
        return all(s.status in (StepStatus.SUCCESS, StepStatus.SKIPPED)
                   for s in self.steps)


class ScrapeWorker(QThread):
    """
    刮削工作流线程

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
            # ===== Step 1: TMM 刮削 =====
            if self.config.enable_tmm_step:
                tmm_result = self._run_tmm_scrape()
                result.steps.append(tmm_result)
            else:
                # 跳过步骤
                tmm_result = StepResult(
                    step=WorkflowStep.TMM_SCRAPE,
                    status=StepStatus.SKIPPED,
                    message="已跳过 TMM 刮削步骤"
                )
                result.steps.append(tmm_result)
                self.step_started.emit("🎬 步骤 1/3：TinyMediaManager 刮削")
                self.step_progress.emit("⏭️ 已跳过 TMM 刮削步骤（用户禁用）")
                self.step_finished.emit("TMM 刮削", True)

            if self._cancelled:
                self._emit_cancelled(result, workflow_start)
                return

            # ===== Step 2: 豆瓣注入 =====
            if self.config.enable_douban_step:
                douban_result, failed_movies = self._run_douban_inject()
                result.steps.append(douban_result)
                result.failed_movies = failed_movies  # 保存失败的电影列表
            else:
                # 跳过步骤
                douban_result = StepResult(
                    step=WorkflowStep.DOUBAN_INJECT,
                    status=StepStatus.SKIPPED,
                    message="已跳过豆瓣注入步骤"
                )
                result.steps.append(douban_result)
                self.step_started.emit("🎭 步骤 2/3：豆瓣评分注入")
                self.step_progress.emit("⏭️ 已跳过豆瓣注入步骤（用户禁用）")
                self.step_finished.emit("豆瓣注入", True)

            if self._cancelled:
                self._emit_cancelled(result, workflow_start)
                return

            # ===== Step 3: 刷新信号 =====
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

    # ─────────────────── Step 1: TMM 刮削 ───────────────────

    def _run_tmm_scrape(self) -> StepResult:
        """运行 TinyMediaManager CLI 刮削"""
        step_result = StepResult(step=WorkflowStep.TMM_SCRAPE)
        step_start = time.time()

        self.step_started.emit("🎬 步骤 1/3：TinyMediaManager 刮削")

        # 构建命令
        tmm_exe = os.path.join(self.config.tmm_path, self.config.tmm_cmd_exe)

        if not os.path.exists(tmm_exe):
            step_result.status = StepStatus.FAILED
            step_result.message = f"TMM 可执行文件不存在: {tmm_exe}"
            self.step_progress.emit(f"❌ {step_result.message}")
            self.step_finished.emit("TMM 刮削", False)
            return step_result

        args = [tmm_exe, "movie"]

        if self.config.tmm_update_all:
            args.append("-u")
        if self.config.tmm_scrape_new:
            args.append("-n")
        if self.config.tmm_scrape_unscraped:
            args.append("--scrapeUnscraped")
        if self.config.tmm_rename:
            args.append("-r")

        cmd_str = " ".join(args)
        self.step_progress.emit(f"执行命令: {cmd_str}")
        self.step_progress.emit(f"超时设置: {self.config.tmm_timeout} 秒")

        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=self.config.tmm_path
            )

            # 实时读取输出
            output_lines = []
            while True:
                if self._cancelled:
                    process.terminate()
                    step_result.status = StepStatus.FAILED
                    step_result.message = "用户取消"
                    break

                line = process.stdout.readline()
                if line == '' and process.poll() is not None:
                    break
                if line:
                    line = line.rstrip()
                    output_lines.append(line)
                    self.step_progress.emit(f"  [TMM] {line}")

            # 检查超时
            elapsed = time.time() - step_start
            if elapsed > self.config.tmm_timeout and process.poll() is None:
                process.terminate()
                step_result.status = StepStatus.FAILED
                step_result.message = f"TMM 刮削超时 ({self.config.tmm_timeout}秒)"
            elif process.returncode == 0:
                step_result.status = StepStatus.SUCCESS
                step_result.message = "TMM 刮削完成"
            else:
                step_result.status = StepStatus.FAILED
                step_result.message = f"TMM 退出码: {process.returncode}"

            step_result.details = "\n".join(output_lines[-50:])  # 保留最后50行

        except FileNotFoundError:
            step_result.status = StepStatus.FAILED
            step_result.message = f"无法找到 TMM: {tmm_exe}"
        except Exception as e:
            step_result.status = StepStatus.FAILED
            step_result.message = f"TMM 执行异常: {e}"

        step_result.elapsed_seconds = time.time() - step_start
        self.step_progress.emit(
            f"{'✅' if step_result.status == StepStatus.SUCCESS else '❌'} "
            f"{step_result.message} (耗时 {step_result.elapsed_seconds:.1f}秒)"
        )
        self.step_finished.emit("TMM 刮削", step_result.status == StepStatus.SUCCESS)
        return step_result

    # ─────────────────── Step 2: 豆瓣注入 ───────────────────

    def _run_douban_inject(self) -> tuple[StepResult, List[FailedMovie]]:
        """运行 TMM_DOUBAN 豆瓣评分注入
        
        Returns:
            (StepResult, List[FailedMovie]): 步骤结果和匹配失败的电影列表
        """
        step_result = StepResult(step=WorkflowStep.DOUBAN_INJECT)
        step_start = time.time()
        failed_movies = []  # 在这里初始化

        self.step_started.emit("🟢 步骤 2/3：豆瓣评分注入")

        # 检查 TMM_DOUBAN 是否可用
        douban_script = os.path.join(
            self.config.douban_tool_path, self.config.douban_script
        )

        if not os.path.exists(douban_script):
            step_result.status = StepStatus.FAILED
            step_result.message = f"豆瓣注入脚本不存在: {douban_script}"
            self.step_progress.emit(f"❌ {step_result.message}")
            self.step_finished.emit("豆瓣注入", False)
            return (step_result, failed_movies)

        # 直接导入 TMM_DOUBAN 的核心类来执行（避免启动 GUI）
        try:
            failed_movies = self._inject_douban_ratings(douban_script, step_result)
        except Exception as e:
            step_result.status = StepStatus.FAILED
            step_result.message = f"豆瓣注入异常: {e}"
            logger.exception("豆瓣注入异常")

        step_result.elapsed_seconds = time.time() - step_start
        self.step_progress.emit(
            f"{'✅' if step_result.status == StepStatus.SUCCESS else '❌'} "
            f"{step_result.message} (耗时 {step_result.elapsed_seconds:.1f}秒)"
        )
        self.step_finished.emit("豆瓣注入", step_result.status == StepStatus.SUCCESS)
        return (step_result, failed_movies)

    def _inject_douban_ratings(self, script_path: str, step_result: StepResult) -> List[FailedMovie]:
        """
        通过导入 TMM_DOUBAN 核心类执行豆瓣注入

        直接复用 DoubanAPI / DoubanAPISelenium + NFOHandler，跳过 GUI。
        
        Returns:
            List[FailedMovie]: 匹配失败的电影列表
        """
        import importlib.util

        # 动态导入 douban_rating_injector_unified 模块
        spec = importlib.util.spec_from_file_location(
            "douban_injector", script_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        NFOHandler = module.NFOHandler
        
        # 根据配置选择 API 模式
        if self.config.douban_mode == "selenium":
            self.step_progress.emit("  使用 Selenium 增强模式")
            
            # 检查 Selenium 是否可用
            if not module.SELENIUM_AVAILABLE:
                step_result.status = StepStatus.FAILED
                step_result.message = "Selenium 未安装，请先安装：pip install selenium webdriver-manager"
                self.step_progress.emit(f"  ❌ {step_result.message}")
                return
            
            DoubanAPISelenium = module.DoubanAPISelenium
            
            try:
                self.step_progress.emit("  正在初始化 Selenium WebDriver...")
                self.step_progress.emit(f"  - 无头模式: {'是' if self.config.selenium_headless else '否'}")
                self.step_progress.emit(f"  - 启用登录: {'是' if self.config.selenium_enable_login else '否'}")
                
                api = DoubanAPISelenium(
                    headless=self.config.selenium_headless,
                    enable_login=self.config.selenium_enable_login,
                    cookie_file=self.config.selenium_cookie_file
                )
                
                if self.config.selenium_enable_login and api.logged_in:
                    self.step_progress.emit("  ✓ 已登录豆瓣账号")
                    
            except Exception as e:
                import traceback
                step_result.status = StepStatus.FAILED
                step_result.message = f"Selenium 初始化失败: {e}"
                self.step_progress.emit(f"  ❌ {step_result.message}")
                self.step_progress.emit(f"  ")
                self.step_progress.emit(f"  常见解决方案：")
                self.step_progress.emit(f"  1. 确保已安装 Chrome 浏览器")
                self.step_progress.emit(f"  2. 检查网络连接（首次使用需下载 ChromeDriver）")
                self.step_progress.emit(f"  3. 尝试关闭防火墙或 VPN")
                self.step_progress.emit(f"  4. 运行命令手动安装：pip install --upgrade selenium webdriver-manager")
                self.step_progress.emit(f"  ")
                self.step_progress.emit(f"  详细错误：")
                for line in traceback.format_exc().split('\n'):
                    if line.strip():
                        self.step_progress.emit(f"    {line}")
                return
        else:
            self.step_progress.emit("  使用普通模式（requests）")
            DoubanAPI = module.DoubanAPI
            cookie = self.config.douban_cookie or None
            api = DoubanAPI(cookie=cookie)
            if cookie:
                self.step_progress.emit("  ✓ 已应用自定义 Cookie")

        nfo_handler = NFOHandler()
        stats = {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0, 'skipped_failed': 0, 'skipped_old': 0}
        failed_movies = []  # 收集匹配失败的电影信息
        
        # 初始化失败记录管理器
        from utils.failed_movies_manager import FailedMoviesManager
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

            # 根据配置过滤 NFO 文件
            filtered_nfo_files = []
            cutoff_time = None
            
            if self.config.douban_inject_new_only and self.config.douban_new_days > 0:
                cutoff_time = datetime.now() - timedelta(days=self.config.douban_new_days)
                self.step_progress.emit(f"  仅处理最近 {self.config.douban_new_days} 天修改的 NFO（{cutoff_time.strftime('%Y-%m-%d %H:%M:%S')} 之后）")
            
            for nfo_file in all_nfo_files:
                # 检查是否在失败列表中
                if self.config.douban_skip_failed and failed_manager.is_failed(nfo_file):
                    stats['skipped_failed'] += 1
                    continue
                
                # 检查修改时间
                if cutoff_time:
                    try:
                        mtime = datetime.fromtimestamp(os.path.getmtime(nfo_file))
                        if mtime < cutoff_time:
                            stats['skipped_old'] += 1
                            continue
                    except Exception:
                        pass  # 获取时间失败则不跳过
                
                filtered_nfo_files.append(nfo_file)
            
            total_found = len(all_nfo_files)
            total = len(filtered_nfo_files)
            stats['total'] = total
            
            self.step_progress.emit(f"找到 {total_found} 个 NFO 文件")
            if stats['skipped_failed'] > 0:
                self.step_progress.emit(f"  跳过 {stats['skipped_failed']} 个已失败的电影")
            if stats['skipped_old'] > 0:
                self.step_progress.emit(f"  跳过 {stats['skipped_old']} 个旧电影（修改时间早于 {self.config.douban_new_days} 天）")
            self.step_progress.emit(f"实际处理 {total} 个 NFO 文件")

            if total == 0:
                step_result.status = StepStatus.SUCCESS
                step_result.message = "没有找到需要处理的 NFO 文件"
                return failed_movies

            import random

            for idx, nfo_file in enumerate(filtered_nfo_files, 1):
                if self._cancelled:
                    self.step_progress.emit("  ⚠️ 用户取消")
                    break

                try:
                    root = nfo_handler.parse_nfo(nfo_file)
                    if root is None:
                        stats['failed'] += 1
                        continue

                    movie_info = nfo_handler.get_movie_info(root)
                    title = movie_info['title']
                    year = movie_info['year']
                    
                    # 尝试获取英文原标题（用于回退搜索）
                    original_title = None
                    try:
                        original_title_elem = root.find('originaltitle')
                        if original_title_elem is not None and original_title_elem.text:
                            original_title = original_title_elem.text.strip()
                    except:
                        pass

                    if not title:
                        stats['failed'] += 1
                        continue

                    # 跳过已有豆瓣评分的
                    if self.config.douban_skip_existing and movie_info['has_douban']:
                        stats['skipped'] += 1
                        continue

                    self.step_progress.emit(
                        f"  [{idx}/{total}] 处理: {title} ({year or '?'})"
                    )

                    # 搜索豆瓣 - 多级回退策略
                    search_result = None
                    search_attempts = []
                    success_strategy = None
                    
                    def verify_year_match(result, expected_year):
                        """验证搜索结果的年份是否匹配"""
                        if not expected_year or not result:
                            return True  # 无年份信息时不验证
                        
                        result_year = result.get('year')
                        if not result_year:
                            return True  # 搜索结果无年份时不验证
                        
                        try:
                            expected = int(expected_year)
                            actual = int(result_year)
                            # 允许1年的误差（考虑不同地区上映时间差异）
                            return abs(expected - actual) <= 1
                        except (ValueError, TypeError):
                            return True  # 年份格式错误时不验证
                    
                    # 策略1: 使用中文名
                    search_result = api.search_movie(title, year)
                    search_attempts.append(('中文名', title))
                    if search_result and verify_year_match(search_result, year):
                        success_strategy = ('中文名', title)
                    elif search_result:
                        # 找到了但年份不匹配
                        self.step_progress.emit(f"    ⚠️ 中文名找到但年份不匹配: {search_result.get('title')} ({search_result.get('year')} ≠ {year})")
                        search_result = None
                    
                    # 策略2: 如果中文名未找到且有英文原名，尝试英文原名
                    if not search_result and original_title and original_title != title:
                        self.step_progress.emit(f"    ⚠️ 中文名未找到，尝试英文原名: {original_title}")
                        search_result = api.search_movie(original_title, year)
                        search_attempts.append(('英文原名', original_title))
                        if search_result and verify_year_match(search_result, year):
                            success_strategy = ('英文原名', original_title)
                        elif search_result:
                            self.step_progress.emit(f"    ⚠️ 英文原名找到但年份不匹配: {search_result.get('title')} ({search_result.get('year')} ≠ {year})")
                            search_result = None
                    
                    # 策略3: 如果还是没找到，尝试去掉副标题（冒号后的部分）
                    if not search_result and (':' in title or '：' in title):
                        # 同时处理中英文冒号
                        simple_title = title.replace('：', ':').split(':')[0].strip()
                        if simple_title and simple_title != title:
                            self.step_progress.emit(f"    ⚠️ 尝试简化标题: {simple_title}")
                            search_result = api.search_movie(simple_title, year)
                            search_attempts.append(('简化标题', simple_title))
                            if search_result and verify_year_match(search_result, year):
                                success_strategy = ('简化标题', simple_title)
                            elif search_result:
                                self.step_progress.emit(f"    ⚠️ 简化标题找到但年份不匹配: {search_result.get('title')} ({search_result.get('year')} ≠ {year})")
                                search_result = None
                    
                    # 策略4: 如果英文名有冒号，也尝试去掉副标题
                    if not search_result and original_title and (':' in original_title or '：' in original_title):
                        simple_original = original_title.replace('：', ':').split(':')[0].strip()
                        if simple_original and simple_original != original_title:
                            self.step_progress.emit(f"    ⚠️ 尝试简化英文标题: {simple_original}")
                            search_result = api.search_movie(simple_original, year)
                            search_attempts.append(('简化英文标题', simple_original))
                            if search_result and verify_year_match(search_result, year):
                                success_strategy = ('简化英文标题', simple_original)
                            elif search_result:
                                self.step_progress.emit(f"    ⚠️ 简化英文标题找到但年份不匹配: {search_result.get('title')} ({search_result.get('year')} ≠ {year})")
                                search_result = None
                    
                    if not search_result:
                        attempts_str = ', '.join([f"{k}({v})" for k, v in search_attempts])
                        self.step_progress.emit(f"    ✗ 未找到豆瓣结果 (已尝试: {attempts_str})")
                        stats['failed'] += 1
                        
                        # 收集失败的电影信息供后续手动匹配
                        failed_movie = FailedMovie(
                            nfo_file=nfo_file,
                            title=title,
                            year=year or "",
                            original_title=original_title or ""
                        )
                        failed_movies.append(failed_movie)
                        
                        # 添加到失败记录
                        if self.config.douban_skip_failed:
                            failed_manager.add_failed(nfo_file, title, year or "")
                        
                        time.sleep(self.config.douban_delay)
                        continue
                    
                    # 显示搜索成功的策略
                    matched_title = search_result.get('title', '未知')
                    matched_year = search_result.get('year', '')
                    year_info = f" ({matched_year})" if matched_year else ""
                    
                    if success_strategy and success_strategy[0] != '中文名':
                        self.step_progress.emit(f"    ✓ 通过{success_strategy[0]}找到: {matched_title}{year_info}")
                    elif matched_year and matched_year != year:
                        # 即使是中文名匹配，如果年份不同也提示
                        self.step_progress.emit(f"    ✓ 匹配: {matched_title}{year_info}")

                    douban_id = search_result['id']

                    # 获取评分
                    delay = self.config.douban_delay + random.uniform(-0.5, 1.0)
                    delay = max(1.0, delay)
                    time.sleep(delay)

                    rating_info = api.get_movie_rating(douban_id)
                    if not rating_info:
                        self.step_progress.emit(f"    ✗ 获取评分失败")
                        stats['failed'] += 1
                        continue

                    rating = rating_info['rating']
                    votes = rating_info['votes']

                    # 注入评分
                    if nfo_handler.inject_douban_data(nfo_file, douban_id, rating, votes):
                        self.step_progress.emit(
                            f"    ✓ {rating}/10 ({votes}票) → {os.path.basename(nfo_file)}"
                        )
                        stats['success'] += 1
                        
                        # 成功后从失败记录中移除（如果存在）
                        if failed_manager.is_failed(nfo_file):
                            failed_manager.remove_failed(nfo_file)
                    else:
                        stats['failed'] += 1

                    # 延迟
                    delay = self.config.douban_delay + random.uniform(-0.5, 1.0)
                    time.sleep(max(1.0, delay))

                except Exception as e:
                    self.step_progress.emit(f"  [{idx}/{total}] 异常: {e}")
                    stats['failed'] += 1

        finally:
            api.close()

        # 构建摘要
        summary_parts = [f"总计 {stats['total']}", f"成功 {stats['success']}", f"失败 {stats['failed']}"]
        if stats['skipped'] > 0:
            summary_parts.append(f"跳过 {stats['skipped']}")
        if stats['skipped_failed'] > 0:
            summary_parts.append(f"跳过失败 {stats['skipped_failed']}")
        if stats['skipped_old'] > 0:
            summary_parts.append(f"跳过旧 {stats['skipped_old']}")
        
        summary = " | ".join(summary_parts)
        self.step_progress.emit(f"  📊 {summary}")

        step_result.status = StepStatus.SUCCESS
        step_result.message = f"豆瓣注入完成 - {summary}"
        step_result.details = summary
        
        return failed_movies

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
        except PermissionError as e:
            self.step_progress.emit(f"  ⚠️ 权限不足: {directory}")
        except Exception as e:
            self.step_progress.emit(f"  ⚠️ 扫描异常: {e}")
        return nfo_files
