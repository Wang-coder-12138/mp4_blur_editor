from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import uuid


class EffectType(str, Enum):
    GAUSSIAN = "gaussian_blur"
    MOSAIC = "mosaic"
    FROSTED = "frosted_glass"


@dataclass
class EffectParams:
    blur_strength: float = 12.0
    block_size: int = 20
    glass_strength: float = 0.45

    def to_dict(self) -> dict[str, Any]:
        return {
            "blur_strength": self.blur_strength,
            "block_size": self.block_size,
            "glass_strength": self.glass_strength,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "EffectParams":
        return EffectParams(
            blur_strength=float(data.get("blur_strength", 12.0)),
            block_size=int(data.get("block_size", 20)),
            glass_strength=float(data.get("glass_strength", 0.45)),
        )


@dataclass
class Region:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = "Region"
    x: float = 0.0
    y: float = 0.0
    width: float = 120.0
    height: float = 80.0
    effect: EffectType = EffectType.GAUSSIAN
    params: EffectParams = field(default_factory=EffectParams)
    start_time: float = 0.0
    end_time: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "effect": self.effect.value,
            "params": self.params.to_dict(),
            "start_time": self.start_time,
            "end_time": self.end_time,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Region":
        effect = EffectType(data.get("effect", EffectType.GAUSSIAN.value))
        return Region(
            id=str(data.get("id") or uuid.uuid4().hex[:8]),
            name=str(data.get("name", "Region")),
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            width=float(data.get("width", 120.0)),
            height=float(data.get("height", 80.0)),
            effect=effect,
            params=EffectParams.from_dict(data.get("params", {})),
            start_time=float(data.get("start_time", 0.0)),
            end_time=float(data.get("end_time", 1.0)),
        )


@dataclass
class Project:
    video_path: str = ""
    video_width: int = 0
    video_height: int = 0
    fps: float = 0.0
    duration: float = 0.0
    regions: list[Region] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_path": self.video_path,
            "video_width": self.video_width,
            "video_height": self.video_height,
            "fps": self.fps,
            "duration": self.duration,
            "regions": [r.to_dict() for r in self.regions],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Project":
        return Project(
            video_path=str(data.get("video_path", "")),
            video_width=int(data.get("video_width", 0)),
            video_height=int(data.get("video_height", 0)),
            fps=float(data.get("fps", 0.0)),
            duration=float(data.get("duration", 0.0)),
            regions=[Region.from_dict(r) for r in data.get("regions", [])],
        )

