from pydantic import BaseModel
from typing import Optional, Any, List
from uuid import UUID
from datetime import datetime

class TopicOut(BaseModel):
    topic_id: str
    title: str
    duration_minutes: int

class UnitOut(BaseModel):
    unit_number: int
    unit_title: str
    topics: List[TopicOut]

class SubjectOut(BaseModel):
    subject_id: str
    subject_title: str
    description: str
    units: List[UnitOut]

class CurriculumOut(BaseModel):
    version: str
    subjects: List[SubjectOut]

class SyllabusOut(BaseModel):
    id: UUID
    original_filename: str
    status: str
    curriculum: Optional[Any] = None
    created_at: datetime
    error_message: Optional[str] = None

    class Config:
        from_attributes = True