from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets
from app.models import EffectType, Region
try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - optional runtime dependency fallback
    cv2 = None
    np = None


class VideoCanvas(QtWidgets.QWidget):
    region_selected = QtCore.Signal(str)
    region_created = QtCore.Signal(float, float, float, float)
    region_geometry_changed = QtCore.Signal(str, float, float, float, float)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.setMouseTracking(True)
        self._frame_image: Optional[QtGui.QImage] = None
        self._video_size = QtCore.QSize(1280, 720)
        self._regions: list[Region] = []
        self._selected_id: Optional[str] = None
        self._current_time = 0.0
        self._draw_rect = QtCore.QRectF()
        self._preview_effects_enabled = False

        self._mode = "idle"  # idle, draw, move, resize
        self._draw_start = QtCore.QPointF()
        self._move_offset = QtCore.QPointF()
        self._resize_handle = -1

    def set_frame(self, image: QtGui.QImage) -> None:
        self._frame_image = image
        if not image.isNull():
            self._video_size = image.size()
        self.update()

    def set_video_size(self, width: int, height: int) -> None:
        if width > 0 and height > 0:
            self._video_size = QtCore.QSize(width, height)
            self.update()

    def set_regions(self, regions: list[Region]) -> None:
        self._regions = regions
        self.update()

    def set_selected_region(self, region_id: Optional[str]) -> None:
        self._selected_id = region_id
        self.update()

    def set_current_time(self, t: float) -> None:
        self._current_time = t
        self.update()

    def set_preview_effects_enabled(self, enabled: bool) -> None:
        self._preview_effects_enabled = enabled
        self.update()

    def _video_draw_rect(self) -> QtCore.QRectF:
        w = float(max(1, self._video_size.width()))
        h = float(max(1, self._video_size.height()))
        ww = float(max(1, self.width()))
        wh = float(max(1, self.height()))
        scale = min(ww / w, wh / h)
        draw_w = w * scale
        draw_h = h * scale
        x = (ww - draw_w) / 2.0
        y = (wh - draw_h) / 2.0
        return QtCore.QRectF(x, y, draw_w, draw_h)

    def _video_to_view(self, p: QtCore.QPointF) -> QtCore.QPointF:
        r = self._video_draw_rect()
        sx = r.width() / max(1.0, float(self._video_size.width()))
        sy = r.height() / max(1.0, float(self._video_size.height()))
        return QtCore.QPointF(r.left() + p.x() * sx, r.top() + p.y() * sy)

    def _view_to_video(self, p: QtCore.QPointF) -> QtCore.QPointF:
        r = self._video_draw_rect()
        if not r.contains(p):
            p = QtCore.QPointF(
                min(max(p.x(), r.left()), r.right()),
                min(max(p.y(), r.top()), r.bottom()),
            )
        sx = max(1.0, float(self._video_size.width())) / r.width()
        sy = max(1.0, float(self._video_size.height())) / r.height()
        return QtCore.QPointF((p.x() - r.left()) * sx, (p.y() - r.top()) * sy)

    def _region_to_view_rect(self, region: Region) -> QtCore.QRectF:
        p1 = self._video_to_view(QtCore.QPointF(region.x, region.y))
        p2 = self._video_to_view(QtCore.QPointF(region.x + region.width, region.y + region.height))
        return QtCore.QRectF(p1, p2).normalized()

    def _handles(self, rect: QtCore.QRectF) -> list[QtCore.QRectF]:
        hs = 8.0
        half = hs / 2.0
        points = [
            rect.topLeft(),
            rect.topRight(),
            rect.bottomRight(),
            rect.bottomLeft(),
        ]
        return [QtCore.QRectF(p.x() - half, p.y() - half, hs, hs) for p in points]

    def _find_region(self, region_id: Optional[str]) -> Optional[Region]:
        if not region_id:
            return None
        for r in self._regions:
            if r.id == region_id:
                return r
        return None

    def _apply_effect_preview(
        self,
        frame_rgba: "np.ndarray",
        region: Region,
    ) -> None:
        if cv2 is None or np is None:
            return
        h, w = frame_rgba.shape[:2]
        x = max(0, min(int(round(region.x)), w - 2))
        y = max(0, min(int(round(region.y)), h - 2))
        rw = max(2, min(int(round(region.width)), w - x))
        rh = max(2, min(int(round(region.height)), h - y))
        if rw < 2 or rh < 2:
            return
        roi = frame_rgba[y:y + rh, x:x + rw, :3]
        if roi.size == 0:
            return

        if region.effect == EffectType.GAUSSIAN:
            sigma = max(0.1, float(region.params.blur_strength))
            k = max(3, int(sigma * 2.8))
            if k % 2 == 0:
                k += 1
            roi[:] = cv2.GaussianBlur(roi, (k, k), sigmaX=sigma, sigmaY=sigma)
        elif region.effect == EffectType.MOSAIC:
            block = max(2, int(region.params.block_size))
            dw = max(1, rw // block)
            dh = max(1, rh // block)
            small = cv2.resize(roi, (dw, dh), interpolation=cv2.INTER_NEAREST)
            roi[:] = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)
        else:
            sigma = max(0.1, float(region.params.blur_strength))
            k = max(3, int(sigma * 2.8))
            if k % 2 == 0:
                k += 1
            blurred = cv2.GaussianBlur(roi, (k, k), sigmaX=sigma, sigmaY=sigma)
            noise_strength = max(0, min(90, int(18 + region.params.glass_strength * 72)))
            noise = np.random.randint(
                -noise_strength,
                noise_strength + 1,
                blurred.shape,
                dtype=np.int16,
            )
            frosted = np.clip(blurred.astype(np.int16) + noise, 0, 255).astype(np.uint8)
            roi[:] = frosted

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(25, 25, 25))
        draw_rect = self._video_draw_rect()
        draw_rect_int = draw_rect.toRect()

        if self._frame_image and not self._frame_image.isNull():
            frame_img = self._frame_image.convertToFormat(QtGui.QImage.Format_RGBA8888)
            if self._preview_effects_enabled and cv2 is not None and np is not None:
                ptr = frame_img.bits()
                bpl = frame_img.bytesPerLine()
                frame_rgba = np.frombuffer(ptr, np.uint8).reshape(frame_img.height(), bpl // 4, 4)[:, : frame_img.width(), :]
                for region in self._regions:
                    if region.start_time <= self._current_time <= region.end_time:
                        self._apply_effect_preview(frame_rgba, region)
            frame_pix = QtGui.QPixmap.fromImage(frame_img)
            painter.drawPixmap(draw_rect_int, frame_pix)
        else:
            painter.fillRect(draw_rect, QtGui.QColor(40, 40, 40))

        for region in self._regions:
            vr = self._region_to_view_rect(region)
            selected = region.id == self._selected_id
            active = region.start_time <= self._current_time <= region.end_time

            color = QtGui.QColor(80, 220, 130, 220 if active else 150)
            if selected:
                color = QtGui.QColor(255, 208, 64, 240)
            pen = QtGui.QPen(color, 2 if selected else 1.5)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRect(vr)
            painter.drawText(vr.topLeft() + QtCore.QPointF(4, -4), region.name)

            if selected:
                painter.setBrush(QtGui.QBrush(QtGui.QColor(255, 208, 64)))
                for h in self._handles(vr):
                    painter.drawRect(h)

        if self._mode == "draw" and not self._draw_rect.isNull():
            painter.setPen(QtGui.QPen(QtGui.QColor(90, 170, 255), 1.5, QtCore.Qt.DashLine))
            painter.drawRect(self._draw_rect.normalized())

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.LeftButton:
            return
        self.setFocus()
        pos = event.position()
        draw_rect = self._video_draw_rect()
        if not draw_rect.contains(pos):
            return

        selected = self._find_region(self._selected_id)
        if selected:
            selected_view = self._region_to_view_rect(selected)
            handles = self._handles(selected_view)
            for i, h in enumerate(handles):
                if h.contains(pos):
                    self._mode = "resize"
                    self._resize_handle = i
                    return
            if selected_view.contains(pos):
                self._mode = "move"
                p_video = self._view_to_video(pos)
                self._move_offset = QtCore.QPointF(p_video.x() - selected.x, p_video.y() - selected.y)
                return

        for r in reversed(self._regions):
            if self._region_to_view_rect(r).contains(pos):
                self._selected_id = r.id
                self.region_selected.emit(r.id)
                self._mode = "move"
                p_video = self._view_to_video(pos)
                self._move_offset = QtCore.QPointF(p_video.x() - r.x, p_video.y() - r.y)
                self.update()
                return

        self._selected_id = None
        self.region_selected.emit("")
        self._mode = "draw"
        self._draw_start = self._view_to_video(pos)
        self._draw_rect = QtCore.QRectF(pos, pos)
        self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        pos = event.position()
        selected = self._find_region(self._selected_id)
        v_w = float(max(1, self._video_size.width()))
        v_h = float(max(1, self._video_size.height()))

        if self._mode == "draw":
            p = self._video_to_view(self._view_to_video(pos))
            p0 = self._video_to_view(self._draw_start)
            self._draw_rect = QtCore.QRectF(p0, p).normalized()
            self.update()
            return

        if not selected:
            return

        if self._mode == "move":
            p_video = self._view_to_video(pos)
            nx = p_video.x() - self._move_offset.x()
            ny = p_video.y() - self._move_offset.y()
            nx = min(max(0.0, nx), v_w - selected.width)
            ny = min(max(0.0, ny), v_h - selected.height)
            selected.x = nx
            selected.y = ny
            self.region_geometry_changed.emit(selected.id, selected.x, selected.y, selected.width, selected.height)
            self.update()
            return

        if self._mode == "resize":
            p_video = self._view_to_video(pos)
            x1 = selected.x
            y1 = selected.y
            x2 = selected.x + selected.width
            y2 = selected.y + selected.height

            if self._resize_handle == 0:  # top-left
                x1, y1 = p_video.x(), p_video.y()
            elif self._resize_handle == 1:  # top-right
                x2, y1 = p_video.x(), p_video.y()
            elif self._resize_handle == 2:  # bottom-right
                x2, y2 = p_video.x(), p_video.y()
            elif self._resize_handle == 3:  # bottom-left
                x1, y2 = p_video.x(), p_video.y()

            x1 = min(max(0.0, x1), v_w - 2.0)
            y1 = min(max(0.0, y1), v_h - 2.0)
            x2 = min(max(2.0, x2), v_w)
            y2 = min(max(2.0, y2), v_h)

            nx = min(x1, x2 - 2.0)
            ny = min(y1, y2 - 2.0)
            nw = max(2.0, abs(x2 - x1))
            nh = max(2.0, abs(y2 - y1))
            selected.x = nx
            selected.y = ny
            selected.width = nw
            selected.height = nh
            self.region_geometry_changed.emit(selected.id, selected.x, selected.y, selected.width, selected.height)
            self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.LeftButton:
            return
        if self._mode == "draw":
            p_end = self._view_to_video(event.position())
            x1, y1 = self._draw_start.x(), self._draw_start.y()
            x2, y2 = p_end.x(), p_end.y()
            x = min(x1, x2)
            y = min(y1, y2)
            w = abs(x2 - x1)
            h = abs(y2 - y1)
            if w >= 4 and h >= 4:
                self.region_created.emit(x, y, w, h)
        self._mode = "idle"
        self._resize_handle = -1
        self._draw_rect = QtCore.QRectF()
        self.update()

