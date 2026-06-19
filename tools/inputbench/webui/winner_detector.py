from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Winner = Literal["p1", "p2", "draw", "unknown"]

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover
    cv2 = None


@dataclass
class WinnerDetectorConfig:
    mode: str = "manual"
    template_dir: str = "./templates"
    roi_enabled: bool = False
    roi_p1: tuple[int, int, int, int] = (0, 0, 0, 0)
    roi_p2: tuple[int, int, int, int] = (0, 0, 0, 0)


class WinnerDetector:
    def __init__(self, config: WinnerDetectorConfig):
        self._cfg = config

    def detect(self, video_path: Path) -> Winner:
        if self._cfg.mode != "auto":
            return "unknown"
        if cv2 is None:
            return "unknown"
        frame = self._read_last_frame(video_path)
        if frame is None:
            return "unknown"

        if self._cfg.roi_enabled:
            roi_p1 = self._crop(frame, self._cfg.roi_p1)
            roi_p2 = self._crop(frame, self._cfg.roi_p2)
            if roi_p1 is not None and roi_p2 is not None:
                p1_score = float(roi_p1.mean())
                p2_score = float(roi_p2.mean())
                if abs(p1_score - p2_score) < 1.0:
                    return "draw"
                return "p1" if p1_score > p2_score else "p2"

        winner = self._detect_by_templates(frame)
        return winner if winner is not None else "unknown"

    def _detect_by_templates(self, frame) -> Winner | None:
        template_dir = Path(self._cfg.template_dir)
        if not template_dir.exists():
            return None
        best_side: Winner | None = None
        best_score = 0.0
        for side in ("p1", "p2"):
            for tpl in template_dir.glob(f"{side}_*.png"):
                tpl_img = cv2.imread(str(tpl), cv2.IMREAD_COLOR)
                if tpl_img is None:
                    continue
                result = cv2.matchTemplate(frame, tpl_img, cv2.TM_CCOEFF_NORMED)
                score = float(result.max()) if result.size else 0.0
                if score > best_score:
                    best_score = score
                    best_side = side
        if best_score < 0.75:
            return None
        return best_side

    def _read_last_frame(self, video_path: Path):
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None
        last = None
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            last = frame
        cap.release()
        return last

    @staticmethod
    def _crop(frame, roi: tuple[int, int, int, int]):
        x, y, w, h = roi
        if w <= 0 or h <= 0:
            return None
        return frame[y : y + h, x : x + w]
