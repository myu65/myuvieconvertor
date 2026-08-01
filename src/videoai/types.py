from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Segment:
        return cls(start=float(data["start"]), end=float(data["end"]), text=str(data["text"]))


@dataclass(frozen=True)
class Transcript:
    language: str
    segments: tuple[Segment, ...]

    @property
    def text(self) -> str:
        return " ".join(segment.text.strip() for segment in self.segments if segment.text.strip())

    def to_dict(self) -> dict[str, Any]:
        return {"language": self.language, "segments": [asdict(item) for item in self.segments]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transcript:
        segments = tuple(Segment.from_dict(item) for item in data.get("segments", []))
        return cls(language=str(data.get("language", "unknown")), segments=segments)
