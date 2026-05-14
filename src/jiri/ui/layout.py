from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def contains(self, point: tuple[int, int]) -> bool:
        px, py = point
        return self.x <= px < self.x + self.width and self.y <= py < self.y + self.height


@dataclass(frozen=True)
class DisplayLayout:
    width: int
    height: int
    face: Rect
    panel: Rect
    top_bar: Rect
    bottom_bar: Rect


def build_layout(width: int = 480, height: int = 320) -> DisplayLayout:
    safe_width = max(240, width)
    safe_height = max(160, height)
    top_h = max(28, int(safe_height * 0.12))
    bottom_h = max(34, int(safe_height * 0.14))
    content_y = top_h
    content_h = safe_height - top_h - bottom_h
    face_w = int(safe_width * 0.58)
    return DisplayLayout(
        width=safe_width,
        height=safe_height,
        face=Rect(0, content_y, face_w, content_h),
        panel=Rect(face_w, content_y, safe_width - face_w, content_h),
        top_bar=Rect(0, 0, safe_width, top_h),
        bottom_bar=Rect(0, safe_height - bottom_h, safe_width, bottom_h),
    )
