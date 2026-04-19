"""从目标窗口采样地图截图，写入原始数据目录。"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

APP_ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core.capture import ScreenCapture
from core.window import WindowManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采样地图截图用于 AI 地块标注")
    parser.add_argument("--window-title", default="", help="窗口标题，默认按包含关系匹配")
    parser.add_argument("--window-hwnd", type=int, default=0, help="窗口句柄，优先级高于窗口标题")
    parser.add_argument("--exact", action="store_true", help="是否精确匹配窗口标题")
    parser.add_argument(
        "--output-dir",
        default=str(AI_ROOT / "datasets" / "plot_det" / "raw" / "images"),
        help="截图输出目录",
    )
    parser.add_argument("--count", type=int, default=300, help="计划保存的截图数量")
    parser.add_argument("--interval", type=float, default=1.2, help="两次截图之间的秒数")
    parser.add_argument(
        "--roi",
        default="",
        help="窗口客户区相对 ROI，格式 x,y,w,h，范围 0 到 1，例如 0.1,0.08,0.8,0.84",
    )
    parser.add_argument("--prefix", default="map", help="输出文件名前缀")
    parser.add_argument("--diff-threshold", type=float, default=2.0, help="相邻截图平均差异阈值，太相似则跳过")
    parser.add_argument("--max-attempts", type=int, default=0, help="最大尝试次数，0 表示自动使用 count 的 8 倍")
    parser.add_argument("--bring-to-front", action="store_true", help="采样前尝试激活窗口")
    parser.add_argument("--settle-seconds", type=float, default=1.0, help="激活窗口后等待秒数")
    return parser.parse_args()


def parse_roi(value: str) -> Optional[Tuple[float, float, float, float]]:
    if not value.strip():
        return None
    parts = [item.strip() for item in value.split(",")]
    if len(parts) != 4:
        raise ValueError("ROI 必须是 x,y,w,h 四个值")
    x, y, w, h = [float(item) for item in parts]
    if w <= 0 or h <= 0:
        raise ValueError("ROI 的宽高必须大于 0")
    if x < 0 or y < 0 or x + w > 1 or y + h > 1:
        raise ValueError("ROI 必须位于 0 到 1 的客户区比例范围内")
    return (x, y, w, h)


def crop_relative_roi(image: np.ndarray, roi: Optional[Tuple[float, float, float, float]]) -> np.ndarray:
    if roi is None:
        return image
    height, width = image.shape[:2]
    x, y, w, h = roi
    left = max(0, min(width - 1, int(round(x * width))))
    top = max(0, min(height - 1, int(round(y * height))))
    right = max(left + 1, min(width, int(round((x + w) * width))))
    bottom = max(top + 1, min(height, int(round((y + h) * height))))
    return image[top:bottom, left:right]


def frame_signature(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
    return small.astype(np.float32)


def mean_signature_difference(previous: Optional[np.ndarray], current: np.ndarray) -> float:
    if previous is None:
        return float("inf")
    return float(np.mean(np.abs(previous - current)))


def save_image(path: Path, image: np.ndarray) -> None:
    success, encoded = cv2.imencode(path.suffix or ".png", image)
    if not success:
        raise ValueError(f"无法编码图片: {path}")
    encoded.tofile(str(path))


def main() -> int:
    args = parse_args()
    roi = parse_roi(args.roi)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "capture_manifest.csv"

    manager = WindowManager()
    window = None
    if args.window_hwnd:
        window = manager.get_window_by_hwnd(int(args.window_hwnd))
    elif args.window_title:
        window = manager.get_window_by_title(args.window_title, exact=args.exact)
    if window is None:
        target_text = str(args.window_hwnd) if args.window_hwnd else args.window_title
        print(f"未找到窗口: {target_text}")
        return 1

    if args.bring_to_front:
        manager.bring_to_front(window.hwnd)
        time.sleep(max(0.0, args.settle_seconds))

    capture = ScreenCapture()
    max_attempts = args.max_attempts if args.max_attempts > 0 else max(args.count * 8, args.count)
    last_signature: Optional[np.ndarray] = None
    attempts = 0
    saved = 0

    write_header = not manifest_path.exists()
    with open(manifest_path, "a", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.writer(file_obj)
        if write_header:
            writer.writerow(["filename", "timestamp", "window_title", "roi", "width", "height", "diff"])

        while saved < args.count and attempts < max_attempts:
            attempts += 1
            image = capture.capture_window(window.hwnd, client_only=True)
            if image is None or getattr(image, "size", 0) == 0:
                print(f"第 {attempts} 次截图失败，等待后重试")
                time.sleep(max(0.1, args.interval))
                continue

            cropped = crop_relative_roi(image, roi)
            signature = frame_signature(cropped)
            diff_value = mean_signature_difference(last_signature, signature)
            if diff_value < args.diff_threshold:
                print(f"第 {attempts} 次截图与上一张过于相似，diff={diff_value:.2f}，跳过")
                time.sleep(max(0.1, args.interval))
                continue

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{args.prefix}_{timestamp}_{saved + 1:04d}.png"
            image_path = output_dir / filename
            save_image(image_path, cropped)

            writer.writerow([
                filename,
                timestamp,
                window.title,
                args.roi or "full",
                cropped.shape[1],
                cropped.shape[0],
                "" if not np.isfinite(diff_value) else f"{diff_value:.4f}",
            ])
            file_obj.flush()

            saved += 1
            last_signature = signature
            print(f"已保存 {saved}/{args.count}: {filename}")
            time.sleep(max(0.1, args.interval))

    print(f"采样结束，成功保存 {saved} 张，尝试 {attempts} 次，输出目录: {output_dir}")
    return 0 if saved > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())