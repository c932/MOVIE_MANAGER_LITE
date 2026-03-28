"""工具类模块。

避免在包导入阶段提前加载依赖 PyQt6 的模块，
以减少无界面环境下（例如测试）的导入失败。
"""

from importlib import import_module

__all__ = ["ConfigManager", "LibraryScanner", "ImageLoader"]


def __getattr__(name):
	if name == "ConfigManager":
		return import_module(".config_manager", __name__).ConfigManager
	if name == "LibraryScanner":
		return import_module(".library_scanner", __name__).LibraryScanner
	if name == "ImageLoader":
		return import_module(".image_loader", __name__).ImageLoader
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
