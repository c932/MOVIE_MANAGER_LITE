#!/usr/bin/env python3
import argparse
from pathlib import Path

from msi_builder_common import ProductConfig, build_product


ROOT = Path(__file__).resolve().parent.parent

MOVIE_CONFIG = ProductConfig(
    root=ROOT,
    product_name="Local Movie Wall",
    product_name_cn="本地电影墙",
    manufacturer="c932",
    upgrade_code="{6C4A8D5B-3F9E-4B1A-9A7C-E8D2F1034567}",
    distribution_name="LocalMovieWall",
    executable_name="LocalMovieWall.exe",
    install_subdir="LocalMovieWall",
    app_data_dir="LocalMovieWall",
    output_prefix="本地电影墙",
    menu_folder="LocalMovieWall",
    shortcut_prefix="MovieWall",
    default_version="3.1.0",
)


def build(version: str = MOVIE_CONFIG.default_version) -> Path:
    return build_product(MOVIE_CONFIG, version)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build MSI installer for 本地电影墙")
    parser.add_argument(
        "--version",
        default=MOVIE_CONFIG.default_version,
        help="Version string, e.g. 3.1.0",
    )
    args = parser.parse_args()
    try:
        build(args.version)
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
