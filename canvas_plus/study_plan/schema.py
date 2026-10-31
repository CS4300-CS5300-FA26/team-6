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