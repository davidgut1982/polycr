"""Shared Pydantic models for the polycr router.

Why: Centralises request/response schemas so the router endpoints, LLM reconciler,
     and tests all share a single source of truth without duplicating field names.
What: Defines EngineResult (per-engine OCR output) and ProcessResponse (full pipeline
      response) as Pydantic BaseModel subclasses.
Test: Instantiate EngineResult(engine="x", text="hello", confidence=90.0) and assert
      .engine == "x"; instantiate ProcessResponse with all fields and assert .dict() is valid.
"""

from typing import Any

from pydantic import BaseModel


class Region(BaseModel):
    """Text region with polygon boundary and per-region confidence."""
    polygon: list[list[float]] = []
    text: str = ""
    confidence: float = 0.0
    angle: int = 0
    angle_confidence: float = 0.0


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
