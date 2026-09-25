#!/usr/bin/env python3
import argparse
from pathlib import Path

from msi_builder_common import ProductConfig, build_product


ROOT = Path(__file__).resolve().parent.parent

GAME_CONFIG = ProductConfig(
    root=ROOT,
    product_name="Local Game Wall",
    product_name_cn="本地游戏墙",
    manufacturer="c932",
    upgrade_code="{D6C975C8-5B50-4C9E-A9F1-8220FEE843D0}",
    distribution_name="LocalGameWall",
    executable_name="LocalGameWall.exe",
    install_subdir="LocalGameWall",
    app_data_dir="LocalGameWall",
    output_prefix="本地游戏墙",
    menu_folder="LocalGameWall",
    shortcut_prefix="GameWall",
    default_version="1.3.7",
)


def build(version: str = GAME_CONFIG.default_version) -> Path:
    return build_product(GAME_CONFIG, version)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build MSI installer for 本地游戏墙")
    parser.add_argument(
        "--version",
        default=GAME_CONFIG.default_version,
        help="Version string, e.g. 1.3.0",
    )
    args = parser.parse_args()
    try:
        build(args.version)
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
