"""交互式地图采样向导。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core.window import WindowManager


def ask_text(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def ask_int(prompt: str, default: int) -> int:
    while True:
        value = ask_text(prompt, str(default))
        try:
            return int(value)
        except ValueError:
            print("请输入整数")


def ask_float(prompt: str, default: float) -> float:
    while True:
        value = ask_text(prompt, str(default))
        try:
            return float(value)
        except ValueError:
            print("请输入数字")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    default_text = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{default_text}]: ").strip().lower()
    if not value:
        return default
    return value in ("y", "yes", "1", "true")


def choose_window() -> str:
    manager = WindowManager()
    windows = manager.get_game_windows()
    if not windows:
        raise RuntimeError("没有找到可用窗口")

    print("可选窗口：")
    for index, window in enumerate(windows, start=1):
        print(f"{index:>2}. {window.title} [{window.width}x{window.height}] class={window.class_name}")

    while True:
        choice = ask_int("请选择窗口序号", 1)
        if 1 <= choice <= len(windows):
            return windows[choice - 1].title
        print("序号超出范围")


def main() -> int:
    parser = argparse.ArgumentParser(description="交互式地图采样向导")
    parser.parse_args()

    print("=== AI 目标采样向导 ===")
    window_title = choose_window()
    count = ask_int("采样张数", 300)
    interval = ask_float("采样间隔秒数", 1.2)
    prefix = ask_text("文件名前缀", "map")
    use_roi = ask_yes_no("是否使用地图 ROI", True)
    roi_value = ""
    if use_roi:
        roi_value = ask_text("输入 ROI x,y,w,h", "0.10,0.08,0.80,0.84")
    bring_to_front = ask_yes_no("采样前是否激活窗口", True)
    diff_threshold = ask_float("相邻截图最小差异阈值", 2.0)

    script_path = Path(__file__).resolve().parent / "sample_map_tiles.py"
    cmd = [
        sys.executable,
        str(script_path),
        "--window-title",
        window_title,
        "--count",
        str(count),
        "--interval",
        str(interval),
        "--prefix",
        prefix,
        "--diff-threshold",
        str(diff_threshold),
    ]
    if roi_value:
        cmd.extend(["--roi", roi_value])
    if bring_to_front:
        cmd.append("--bring-to-front")

    print("\n即将执行：")
    print(" ".join(f'"{part}"' if " " in part else part for part in cmd))
    print()
    completed = subprocess.run(cmd, cwd=str(APP_ROOT))
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())