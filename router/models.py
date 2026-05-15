"""Shared Pydantic models for the polycr router."""

from typing import Any

from pydantic import BaseModel


class Region(BaseModel):
    """Text region with polygon boundary and per-region confidence."""
    polygon: list[list[float]] = []
    text: str = ""
    confidence: float = 0.0


class EngineResult(BaseModel):
    """Single engine OCR output, including an optional error field."""
    engine: str
    text: str = ""
    confidence: float = 0.0
    error: str = ""
    regions: list[Region] = []


class ProcessResponse(BaseModel):
    """Full pipeline response returned by POST /process."""
    text: str
    structured: dict[str, Any]
    ocr_raw: list[EngineResult]
    engines_used: list[str]
    engines_failed: list[str]
