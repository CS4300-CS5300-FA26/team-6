"""Pydantic response contracts for AI-generated study plans."""

from datetime import datetime

from pydantic import BaseModel, Field


class StudySessionProposal(BaseModel):
    """One proposed assignment session returned by the AI."""

    assignment_id: int
    start: datetime
    end: datetime
    late: bool


class StudyPlan(BaseModel):
    """Structured AI response containing sessions and planning notices."""

    sessions: list[StudySessionProposal] = Field(min_length=1)
    notices: list[str] = Field(default_factory=list)


class EffortEstimate(BaseModel):
    """Structured AI response for an assignment effort estimate."""

    # Estimated amount of study/work time required, in minutes.
    # The value must be positive.
    estimated_minutes: int = Field(gt=0)

    # Short explanation of why the AI selected this estimate.
    reason: str = Field(min_length=1)
