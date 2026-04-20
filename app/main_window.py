from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

try:
    import cv2
except Exception:  # pragma: no cover - optional runtime dependency fallback
    cv2 = None
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink

from app.ffmpeg_exporter import export_mp4, probe_video, resolve_ffmpeg_tools
from app.models import EffectType, Project, Region
from app.project_io import load_project, save_project
from app.video_canvas import VideoCanvas


class ExportWorker(QtCore.QObject):
    finished = QtCore.Signal(bool, str)

    def __init__(self, project: Project, output_path: str, ffmpeg_bin: str) -> None:
        super().__init__()
        self.project = project
        self.output_path = output_path
        self.ffmpeg_bin = ffmpeg_bin

    @QtCore.Slot()
    def run(self) -> None:
        try:
            ok, msg = export_mp4(self.project, self.output_path, ffmpeg_bin=self.ffmpeg_bin)
        except Exception as e:
            ok, msg = False, f"导出异常：{e}"
        self.finished.emit(ok, msg)


class MainWindow(QtWidgets.QMainWindow):
    BLUR_MIN = 1.0
    BLUR_MAX = 45.0
    BLOCK_MIN = 4
    BLOCK_MAX = 80

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MP4 视频区域模糊编辑器")
        self.resize(1400, 860)

        self.project = Project()
        self.selected_region_id: Optional[str] = None
        self._updating_ui = False
        self._syncing_slider = False
        self.ffmpeg_bin, self.ffprobe_bin = resolve_ffmpeg_tools()
        self.export_thread: Optional[QtCore.QThread] = None
        self.export_worker: Optional[ExportWorker] = None
        self.export_progress: Optional[QtWidgets.QProgressDialog] = None
        self._export_out_path = ""

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)

        self._build_ui()
        self._connect_signals()

    def _make_strength_slider(self) -> QtWidgets.QSlider:
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setSingleStep(1)
        slider.setPageStep(5)
        return slider

    def _wrap_strength_row(self, slider: QtWidgets.QSlider) -> QtWidgets.QWidget:
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QtWidgets.QLabel("弱"))
        row.addWidget(slider, 1)
        row.addWidget(QtWidgets.QLabel("强"))
        widget = QtWidgets.QWidget()
        widget.setLayout(row)
        return widget

    def _slider_to_blur(self, value: int) -> float:
        ratio = max(0.0, min(1.0, value / 100.0))
        return self.BLUR_MIN + ratio * (self.BLUR_MAX - self.BLUR_MIN)

    def _blur_to_slider(self, value: float) -> int:
        v = max(self.BLUR_MIN, min(self.BLUR_MAX, value))
        return int(round((v - self.BLUR_MIN) * 100.0 / (self.BLUR_MAX - self.BLUR_MIN)))

    def _slider_to_block(self, value: int) -> int:
        ratio = max(0.0, min(1.0, value / 100.0))
        return int(round(self.BLOCK_MIN + ratio * (self.BLOCK_MAX - self.BLOCK_MIN)))

    def _block_to_slider(self, value: int) -> int:
        v = max(self.BLOCK_MIN, min(self.BLOCK_MAX, value))
        return int(round((v - self.BLOCK_MIN) * 100.0 / (self.BLOCK_MAX - self.BLOCK_MIN)))

    def _slider_to_glass(self, value: int) -> float:
        return max(0.0, min(1.0, value / 100.0))

    def _glass_to_slider(self, value: float) -> int:
        v = max(0.0, min(1.0, value))
        return int(round(v * 100.0))

    def _build_ui(self) -> None:
        root = QtWidgets.QWidget(self)
        self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)

        toolbar = QtWidgets.QHBoxLayout()
        self.btn_import = QtWidgets.QPushButton("导入 MP4")
        self.btn_save_project = QtWidgets.QPushButton("保存工程 JSON")
        self.btn_load_project = QtWidgets.QPushButton("加载工程 JSON")
        self.lb_hint = QtWidgets.QLabel("提示：在视频区域内按住鼠标左键并拖动，可放置矩形。")
        self.btn_export = QtWidgets.QPushButton("导出 MP4")
        toolbar.addWidget(self.btn_import)
        toolbar.addWidget(self.btn_save_project)
        toolbar.addWidget(self.btn_load_project)
        toolbar.addWidget(self.lb_hint)
        toolbar.addStretch(1)
        toolbar.addWidget(self.btn_export)
        layout.addLayout(toolbar)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        layout.addWidget(splitter, 1)

        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        self.canvas = VideoCanvas()
        self.canvas.setMinimumSize(800, 450)
        left_layout.addWidget(self.canvas, 1)

        controls = QtWidgets.QHBoxLayout()
        self.btn_play_pause = QtWidgets.QPushButton("播放")
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.time_label = QtWidgets.QLabel("00:00.000 / 00:00.000")
        controls.addWidget(self.btn_play_pause)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        left_layout.addLayout(controls)
        splitter.addWidget(left)

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)

        list_row = QtWidgets.QHBoxLayout()
        list_row.addWidget(QtWidgets.QLabel("矩形框列表"))
        self.btn_delete_region = QtWidgets.QPushButton("删除选中")
        list_row.addStretch(1)
        list_row.addWidget(self.btn_delete_region)
        right_layout.addLayout(list_row)

        self.region_list = QtWidgets.QListWidget()
        right_layout.addWidget(self.region_list, 1)

        form = QtWidgets.QFormLayout()
        self.ed_name = QtWidgets.QLineEdit()
        self.cb_effect = QtWidgets.QComboBox()
        self.cb_effect.addItems(
            [
                "Gaussian Blur",
                "Mosaic",
                "Frosted Glass",
            ]
        )

        self.stack_params = QtWidgets.QStackedWidget()

        page_blur = QtWidgets.QWidget()
        p1 = QtWidgets.QFormLayout(page_blur)
        self.sl_blur = self._make_strength_slider()
        p1.addRow("blur strength", self._wrap_strength_row(self.sl_blur))

        page_mosaic = QtWidgets.QWidget()
        p2 = QtWidgets.QFormLayout(page_mosaic)
        self.sl_block = self._make_strength_slider()
        p2.addRow("block size", self._wrap_strength_row(self.sl_block))

        page_frosted = QtWidgets.QWidget()
        p3 = QtWidgets.QFormLayout(page_frosted)
        self.sl_f_blur = self._make_strength_slider()
        self.sl_f_glass = self._make_strength_slider()
        p3.addRow("blur strength", self._wrap_strength_row(self.sl_f_blur))
        p3.addRow("glass strength", self._wrap_strength_row(self.sl_f_glass))

        self.stack_params.addWidget(page_blur)
        self.stack_params.addWidget(page_mosaic)
        self.stack_params.addWidget(page_frosted)

        self.sp_start = QtWidgets.QDoubleSpinBox()
        self.sp_end = QtWidgets.QDoubleSpinBox()
        self.sp_start.setDecimals(3)
        self.sp_end.setDecimals(3)
        self.sp_start.setRange(0.0, 86400.0)
        self.sp_end.setRange(0.0, 86400.0)
        self.sp_start.setSingleStep(0.1)
        self.sp_end.setSingleStep(0.1)
        self.btn_set_start_now = QtWidgets.QPushButton("读入当前时间")
        self.btn_set_end_now = QtWidgets.QPushButton("读入当前时间")
        self.btn_set_start_now.setToolTip("将当前播放时间写入 start time")
        self.btn_set_end_now.setToolTip("将当前播放时间写入 end time")

        start_row = QtWidgets.QHBoxLayout()
        start_row.setContentsMargins(0, 0, 0, 0)
        start_row.addWidget(self.sp_start, 1)
        start_row.addWidget(self.btn_set_start_now)
        start_wrap = QtWidgets.QWidget()
        start_wrap.setLayout(start_row)

        end_row = QtWidgets.QHBoxLayout()
        end_row.setContentsMargins(0, 0, 0, 0)
        end_row.addWidget(self.sp_end, 1)
        end_row.addWidget(self.btn_set_end_now)
        end_wrap = QtWidgets.QWidget()
        end_wrap.setLayout(end_row)

        form.addRow("name", self.ed_name)
        form.addRow("effect type", self.cb_effect)
        form.addRow("effect params", self.stack_params)
        form.addRow("start time (s)", start_wrap)
        form.addRow("end time (s)", end_wrap)
        right_layout.addLayout(form)

        right.setMinimumWidth(380)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 2)

    def _connect_signals(self) -> None:
        self.btn_import.clicked.connect(self.import_video)
        self.btn_play_pause.clicked.connect(self.toggle_play_pause)
        self.slider.valueChanged.connect(self.on_slider_value_changed)
        self.btn_save_project.clicked.connect(self.on_save_project)
        self.btn_load_project.clicked.connect(self.on_load_project)
        self.btn_export.clicked.connect(self.on_export)

        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.player.playbackStateChanged.connect(self.on_playback_state_changed)
        self.sink.videoFrameChanged.connect(self.on_video_frame)

        self.canvas.region_selected.connect(self.on_canvas_selected)
        self.canvas.region_created.connect(self.on_canvas_region_created)
        self.canvas.region_geometry_changed.connect(self.on_canvas_geometry_changed)

        self.region_list.currentRowChanged.connect(self.on_region_list_changed)
        self.btn_delete_region.clicked.connect(self.delete_selected_region)

        self.ed_name.textEdited.connect(self.on_prop_changed)
        self.cb_effect.currentIndexChanged.connect(self.on_effect_changed)
        self.sl_blur.valueChanged.connect(self.on_prop_changed)
        self.sl_block.valueChanged.connect(self.on_prop_changed)
        self.sl_f_blur.valueChanged.connect(self.on_prop_changed)
        self.sl_f_glass.valueChanged.connect(self.on_prop_changed)
        self.sp_start.valueChanged.connect(self.on_prop_changed)
        self.sp_end.valueChanged.connect(self.on_prop_changed)
        self.btn_set_start_now.clicked.connect(self.set_start_from_current_time)
        self.btn_set_end_now.clicked.connect(self.set_end_from_current_time)

    def _get_selected_region(self) -> Optional[Region]:
        if not self.selected_region_id:
            return None
        for r in self.project.regions:
            if r.id == self.selected_region_id:
                return r
        return None

    def _format_time(self, ms: int) -> str:
        s = max(0, ms) / 1000.0
        m = int(s // 60)
        sec = s % 60
        return f"{m:02d}:{sec:06.3f}"

    def _refresh_time_label(self, pos: int) -> None:
        self.time_label.setText(f"{self._format_time(pos)} / {self._format_time(self.slider.maximum())}")

    def _refresh_region_list(self) -> None:
        self.region_list.blockSignals(True)
        self.region_list.clear()
        for r in self.project.regions:
            t = f"{r.start_time:.2f}-{r.end_time:.2f}s"
            self.region_list.addItem(f"{r.name} | {r.effect.value} | {t}")
        self.region_list.blockSignals(False)

        if self.selected_region_id:
            for idx, r in enumerate(self.project.regions):
                if r.id == self.selected_region_id:
                    self.region_list.setCurrentRow(idx)
                    break
        self.canvas.set_regions(self.project.regions)

    def _sync_props_from_region(self, region: Optional[Region]) -> None:
        self._updating_ui = True
        enabled = region is not None
        for widget in [
            self.ed_name,
            self.cb_effect,
            self.sl_blur,
            self.sl_block,
            self.sl_f_blur,
            self.sl_f_glass,
            self.sp_start,
            self.sp_end,
            self.btn_set_start_now,
            self.btn_set_end_now,
            self.btn_delete_region,
        ]:
            widget.setEnabled(enabled)
        if region:
            self.ed_name.setText(region.name)
            effect_idx = {
                EffectType.GAUSSIAN: 0,
                EffectType.MOSAIC: 1,
                EffectType.FROSTED: 2,
            }[region.effect]
            self.cb_effect.setCurrentIndex(effect_idx)
            self.stack_params.setCurrentIndex(effect_idx)
            self.sl_blur.setValue(self._blur_to_slider(region.params.blur_strength))
            self.sl_block.setValue(self._block_to_slider(region.params.block_size))
            self.sl_f_blur.setValue(self._blur_to_slider(region.params.blur_strength))
            self.sl_f_glass.setValue(self._glass_to_slider(region.params.glass_strength))
            self.sp_start.setValue(region.start_time)
            self.sp_end.setValue(region.end_time)
        else:
            self.ed_name.setText("")
            self.stack_params.setCurrentIndex(0)
        self._updating_ui = False

    @QtCore.Slot()
    def import_video(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 MP4 视频", "", "MP4 Video (*.mp4)")
        if not path:
            return
        self._load_video(path, keep_regions=False)

    def _load_video(self, path: str, keep_regions: bool) -> None:
        try:
            info = probe_video(path, ffprobe_bin=self.ffprobe_bin)
        except FileNotFoundError:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                "读取视频信息失败：找不到 ffprobe。\n请确认 ffmpeg\\ffprobe.exe 存在，或安装 FFmpeg 并加入 PATH。",
            )
            return
        except subprocess.CalledProcessError:
            QtWidgets.QMessageBox.critical(self, "错误", "无法读取视频信息，请确保 ffprobe 可用。")
            return
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "错误", f"读取视频信息失败：{e}")
            return

        if not keep_regions:
            self.project = Project()

        self.project.video_path = os.path.abspath(path)
        self.project.video_width = info.width
        self.project.video_height = info.height
        self.project.fps = info.fps
        self.project.duration = info.duration
        self.canvas.set_video_size(info.width, info.height)
        self.canvas.set_regions(self.project.regions)

        self.player.setSource(QtCore.QUrl.fromLocalFile(self.project.video_path))
        self.slider.setRange(0, int(round(info.duration * 1000)))
        self._syncing_slider = True
        self.slider.setValue(0)
        self._syncing_slider = False
        self._refresh_time_label(0)
        self.player.pause()
        self.player.setPosition(0)
        self.canvas.set_current_time(0.0)
        self._load_first_frame(path)
        self.statusBar().showMessage(
            f"已加载: {os.path.basename(path)} ({info.width}x{info.height}, {info.fps:.3f}fps, {info.duration:.3f}s)"
        )

        self.selected_region_id = None
        self.canvas.set_selected_region(None)
        self._refresh_region_list()
        self._sync_props_from_region(None)

    @QtCore.Slot()
    def toggle_play_pause(self) -> None:
        if self.player.source().isEmpty():
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _load_first_frame(self, path: str) -> None:
        if cv2 is None:
            return
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, c = rgb.shape
        if c != 3:
            return
        image = QtGui.QImage(rgb.data, w, h, w * 3, QtGui.QImage.Format_RGB888).copy()
        self.canvas.set_frame(image)

    @QtCore.Slot(int)
    def on_slider_value_changed(self, value: int) -> None:
        if self._syncing_slider:
            return
        self.player.setPosition(value)
        self.canvas.set_current_time(value / 1000.0)
        self._refresh_time_label(value)

    @QtCore.Slot(int)
    def on_position_changed(self, pos: int) -> None:
        if not self.slider.isSliderDown():
            self._syncing_slider = True
            self.slider.setValue(pos)
            self._syncing_slider = False
        self.canvas.set_current_time(pos / 1000.0)
        self._refresh_time_label(pos)

    @QtCore.Slot(int)
    def on_duration_changed(self, ms: int) -> None:
        if ms > 0:
            self.slider.setMaximum(ms)
            self.project.duration = ms / 1000.0
            self._refresh_time_label(self.slider.value())

    @QtCore.Slot(QMediaPlayer.PlaybackState)
    def on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.btn_play_pause.setText("暂停" if state == QMediaPlayer.PlayingState else "播放")
        self.canvas.set_preview_effects_enabled(state == QMediaPlayer.PlayingState)

    @QtCore.Slot(QVideoFrame)
    def on_video_frame(self, frame: QVideoFrame) -> None:
        image = frame.toImage()
        if image.isNull():
            return
        self.canvas.set_frame(image)

    @QtCore.Slot(str)
    def on_canvas_selected(self, region_id: str) -> None:
        self.selected_region_id = region_id or None
        self.canvas.set_selected_region(self.selected_region_id)
        self._refresh_region_list()
        self._sync_props_from_region(self._get_selected_region())

    @QtCore.Slot(float, float, float, float)
    def on_canvas_region_created(self, x: float, y: float, w: float, h: float) -> None:
        if not self.project.video_path:
            return
        idx = len(self.project.regions) + 1
        now = self.player.position() / 1000.0
        region = Region(
            name=f"Region {idx}",
            x=x,
            y=y,
            width=w,
            height=h,
            effect=EffectType.GAUSSIAN,
            start_time=now,
            end_time=max(now + 1.0, self.project.duration),
        )
        self.project.regions.append(region)
        self.selected_region_id = region.id
        self.canvas.set_selected_region(region.id)
        self._refresh_region_list()
        self._sync_props_from_region(region)

    @QtCore.Slot(str, float, float, float, float)
    def on_canvas_geometry_changed(self, region_id: str, x: float, y: float, w: float, h: float) -> None:
        for r in self.project.regions:
            if r.id == region_id:
                r.x, r.y, r.width, r.height = x, y, w, h
                break
        self._refresh_region_list()

    @QtCore.Slot(int)
    def on_region_list_changed(self, row: int) -> None:
        if row < 0 or row >= len(self.project.regions):
            self.selected_region_id = None
            self.canvas.set_selected_region(None)
            self._sync_props_from_region(None)
            return
        region = self.project.regions[row]
        self.selected_region_id = region.id
        self.canvas.set_selected_region(region.id)
        self._sync_props_from_region(region)

    @QtCore.Slot()
    def delete_selected_region(self) -> None:
        if not self.selected_region_id:
            return
        self.project.regions = [r for r in self.project.regions if r.id != self.selected_region_id]
        self.selected_region_id = None
        self.canvas.set_selected_region(None)
        self._refresh_region_list()
        self._sync_props_from_region(None)

    @QtCore.Slot()
    def on_effect_changed(self) -> None:
        if self._updating_ui:
            return
        self.stack_params.setCurrentIndex(self.cb_effect.currentIndex())
        self.on_prop_changed()

    @QtCore.Slot()
    def on_prop_changed(self) -> None:
        if self._updating_ui:
            return
        region = self._get_selected_region()
        if not region:
            return

        region.name = self.ed_name.text().strip() or region.name
        idx = self.cb_effect.currentIndex()
        if idx == 0:
            region.effect = EffectType.GAUSSIAN
            region.params.blur_strength = self._slider_to_blur(self.sl_blur.value())
        elif idx == 1:
            region.effect = EffectType.MOSAIC
            region.params.block_size = self._slider_to_block(self.sl_block.value())
        else:
            region.effect = EffectType.FROSTED
            region.params.blur_strength = self._slider_to_blur(self.sl_f_blur.value())
            region.params.glass_strength = self._slider_to_glass(self.sl_f_glass.value())

        start = self.sp_start.value()
        end = self.sp_end.value()
        if end < start:
            end = start
            self.sp_end.blockSignals(True)
            self.sp_end.setValue(end)
            self.sp_end.blockSignals(False)
        region.start_time = start
        region.end_time = end

        self._refresh_region_list()
        self.canvas.update()

    @QtCore.Slot()
    def on_save_project(self) -> None:
        if not self.project.video_path:
            QtWidgets.QMessageBox.information(self, "提示", "请先导入视频。")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "保存工程", "", "JSON (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        save_project(path, self.project)
        self.statusBar().showMessage(f"工程已保存: {path}")

    @QtCore.Slot()
    def on_load_project(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "加载工程", "", "JSON (*.json)")
        if not path:
            return
        try:
            project = load_project(path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "错误", f"加载工程失败：{e}")
            return

        self.project = project
        if self.project.video_path and os.path.exists(self.project.video_path):
            self._load_video(self.project.video_path, keep_regions=True)
            self.canvas.set_regions(self.project.regions)
            self._refresh_region_list()
        else:
            QtWidgets.QMessageBox.warning(self, "提示", "工程中的视频路径不存在，请重新导入视频。")
            self._refresh_region_list()
            self.canvas.set_regions(self.project.regions)

    @QtCore.Slot()
    def on_export(self) -> None:
        if not self.project.video_path:
            QtWidgets.QMessageBox.information(self, "提示", "请先导入视频。")
            return
        if self.export_thread and self.export_thread.isRunning():
            QtWidgets.QMessageBox.information(self, "提示", "导出正在进行中，请稍候。")
            return
        base_dir = os.path.dirname(self.project.video_path)
        base_name = os.path.splitext(os.path.basename(self.project.video_path))[0]
        default_out = os.path.join(base_dir, f"{base_name}_blur.mp4")
        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "导出 MP4", default_out, "MP4 Video (*.mp4)")
        if not out_path:
            return
        if not out_path.lower().endswith(".mp4"):
            out_path += ".mp4"

        self._export_out_path = out_path
        self.btn_export.setEnabled(False)
        self.export_progress = QtWidgets.QProgressDialog("正在导出，请稍候...", None, 0, 0, self)
        self.export_progress.setWindowTitle("导出中")
        self.export_progress.setCancelButton(None)
        self.export_progress.setWindowModality(QtCore.Qt.WindowModal)
        self.export_progress.setAutoClose(False)
        self.export_progress.setAutoReset(False)
        self.export_progress.show()
        QtWidgets.QApplication.processEvents()

        self.export_thread = QtCore.QThread(self)
        self.export_worker = ExportWorker(self.project, out_path, self.ffmpeg_bin)
        self.export_worker.moveToThread(self.export_thread)
        self.export_thread.started.connect(self.export_worker.run)
        self.export_worker.finished.connect(self._on_export_done)
        self.export_worker.finished.connect(self.export_thread.quit)
        self.export_worker.finished.connect(self.export_worker.deleteLater)
        self.export_thread.finished.connect(self.export_thread.deleteLater)
        self.export_thread.start()

    @QtCore.Slot(bool, str)
    def _on_export_done(self, ok: bool, msg: str) -> None:
        if self.export_progress:
            self.export_progress.close()
            self.export_progress.deleteLater()
            self.export_progress = None
        self.btn_export.setEnabled(True)
        if ok:
            QtWidgets.QMessageBox.information(self, "导出完成", f"已导出：{self._export_out_path}")
            self.statusBar().showMessage(f"导出完成: {self._export_out_path}")
        else:
            QtWidgets.QMessageBox.critical(self, "导出失败", msg)
        self.export_worker = None
        self.export_thread = None

    @QtCore.Slot()
    def set_start_from_current_time(self) -> None:
        if self._updating_ui:
            return
        t = max(0.0, self.player.position() / 1000.0)
        self.sp_start.setValue(t)

    @QtCore.Slot()
    def set_end_from_current_time(self) -> None:
        if self._updating_ui:
            return
        t = max(0.0, self.player.position() / 1000.0)
        self.sp_end.setValue(t)


def run() -> None:
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

