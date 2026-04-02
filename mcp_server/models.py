from typing import Any, Literal
from pydantic import BaseModel


class ParameterDef(BaseModel):
    name: str
    type: str  # string, integer, float, boolean
    required: bool = False
    default: Any = None
    description: str = ""
    enum: list[Any] | None = None
    min: float | None = None
    max: float | None = None


class CapabilitySummary(BaseModel):
    name: str
    display_name: str
    description: str
    category: str
    parameters: list[ParameterDef]


class JobStatus(BaseModel):
    prompt_id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: float = 0.0
    result_files: list[dict[str, Any]] = []
    error: str | None = None
