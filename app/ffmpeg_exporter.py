from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.models import EffectType, Project, Region


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float


def _is_executable(path: Path) -> bool:
    return path.exists() and path.is_file()


def resolve_ffmpeg_tools() -> tuple[str, str]:
    exe_suffix = ".exe" if os.name == "nt" else ""
    ffmpeg_name = f"ffmpeg{exe_suffix}"
    ffprobe_name = f"ffprobe{exe_suffix}"

    env_ffmpeg = os.environ.get("FFMPEG_BIN", "").strip()
    env_ffprobe = os.environ.get("FFPROBE_BIN", "").strip()
    if env_ffmpeg and env_ffprobe:
        return env_ffmpeg, env_ffprobe

    here = Path(__file__).resolve()
    root = here.parent.parent  # mp4_blur_editor
    candidates = [
        root / "ffmpeg",
        root.parent / "Propainter1.6" / "ffmpeg",
    ]
    for base in candidates:
        ffmpeg_path = base / ffmpeg_name
        ffprobe_path = base / ffprobe_name
        if _is_executable(ffmpeg_path) and _is_executable(ffprobe_path):
            return str(ffmpeg_path), str(ffprobe_path)

    return ("ffmpeg", "ffprobe")


def probe_video(path: str, ffprobe_bin: str | None = None) -> VideoInfo:
    _, auto_ffprobe = resolve_ffmpeg_tools()
    ffprobe_cmd = ffprobe_bin or auto_ffprobe
    cmd = [
        ffprobe_cmd,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    out = subprocess.check_output(cmd, text=True).strip().splitlines()
    if len(out) < 4:
        raise RuntimeError("ffprobe output invalid")
    width = int(float(out[0]))
    height = int(float(out[1]))
    fps_num, fps_den = out[2].split("/")
    fps = float(fps_num) / float(fps_den)
    duration = float(out[3])
    return VideoInfo(width=width, height=height, fps=fps, duration=duration)


def _clip_region(r: Region, w: int, h: int) -> tuple[int, int, int, int]:
    x = max(0, min(int(round(r.x)), w - 2))
    y = max(0, min(int(round(r.y)), h - 2))
    rw = max(2, min(int(round(r.width)), w - x))
    rh = max(2, min(int(round(r.height)), h - y))
    return x, y, rw, rh


def build_filter_complex(project: Project) -> tuple[str, str]:
    filters: list[str] = []
    # Keep effect processing in RGB domain to match OpenCV preview and avoid
    # chroma-subsampling edge artifacts (e.g. green lines) during region overlay.
    filters.append("[0:v]format=rgb24[src]")
    current = "src"

    for idx, region in enumerate(project.regions):
        x, y, rw, rh = _clip_region(region, project.video_width, project.video_height)
        start = max(0.0, min(region.start_time, project.duration))
        end = max(start, min(region.end_time, project.duration))
        enable = f"between(t,{start:.3f},{end:.3f})"
        base_tag = f"b{idx}"
        crop_in_tag = f"ci{idx}"
        crop_tag = f"c{idx}"
        out_tag = f"v{idx}"
        filters.append(f"[{current}]split=2[{base_tag}][{crop_in_tag}]")

        if region.effect == EffectType.GAUSSIAN:
            sigma = max(0.1, float(region.params.blur_strength))
            filters.append(f"[{crop_in_tag}]crop={rw}:{rh}:{x}:{y},gblur=sigma={sigma:.2f}[{crop_tag}]")
        elif region.effect == EffectType.MOSAIC:
            block = max(2, int(region.params.block_size))
            down_w = max(1, rw // block)
            down_h = max(1, rh // block)
            filters.append(
                f"[{crop_in_tag}]crop={rw}:{rh}:{x}:{y},"
                f"scale={down_w}:{down_h}:flags=neighbor,"
                f"scale={rw}:{rh}:flags=neighbor[{crop_tag}]"
            )
        else:
            sigma = max(0.1, float(region.params.blur_strength))
            noise = max(0, min(100, int(region.params.glass_strength * 100)))
            filters.append(
                f"[{crop_in_tag}]crop={rw}:{rh}:{x}:{y},"
                f"gblur=sigma={sigma:.2f},noise=alls={noise}:allf=t+u[{crop_tag}]"
            )

        filters.append(f"[{base_tag}][{crop_tag}]overlay={x}:{y}:format=rgb:enable='{enable}'[{out_tag}]")
        current = out_tag

    return ";".join(filters), current


def export_mp4(
    project: Project,
    output_path: str,
    ffmpeg_bin: str | None = None,
    crf: int = 16,
    preset: str = "slow",
) -> tuple[bool, str]:
    if not project.video_path:
        return False, "No input video selected."
    if not output_path.lower().endswith(".mp4"):
        return False, "Output must be mp4."

    auto_ffmpeg, _ = resolve_ffmpeg_tools()
    ffmpeg_cmd = ffmpeg_bin or auto_ffmpeg

    if not project.regions:
        cmd = [
            ffmpeg_cmd,
            "-y",
            "-i",
            project.video_path,
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            output_path,
        ]
        run = subprocess.run(cmd, text=True, capture_output=True)
        if run.returncode != 0:
            return False, run.stderr[-2000:]
        return True, "Export done."

    filter_complex, last_video = build_filter_complex(project)
    cmd = [
        ffmpeg_cmd,
        "-y",
        "-i",
        project.video_path,
        "-filter_complex",
        filter_complex,
        "-map",
        f"[{last_video}]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        output_path,
    ]
    run = subprocess.run(cmd, text=True, capture_output=True)
    if run.returncode != 0:
        return False, f"FFmpeg failed:\n{run.stderr[-3000:]}\n\nCMD:\n{shlex.join(cmd)}"
    return True, "Export done."

