import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Text, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from app.db.base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    syllabi = relationship("Syllabus", back_populates="owner")

class Syllabus(Base):
    __tablename__ = "syllabi"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    original_filename = Column(String(512), nullable=False)
    stored_path = Column(String(1024), nullable=False)
    file_type = Column(String(50), nullable=False)          # pdf / image / text
    status = Column(String(50), default="uploaded")         # uploaded | processing | parsed | failed
    phase = Column(String(20), default="extract")           # extract | distribute | generate | done | error
    raw_text = Column(Text, nullable=True)
    curriculum = Column(JSON, nullable=True)                # the subject/unit/topic json goes here
    knowledge_graph = Column(JSON, nullable=True)            # networkx graph saved as node_link_data
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="syllabi")
    units = relationship("Unit", back_populates="syllabus", cascade="all, delete-orphan")

class Unit(Base):
    __tablename__ = "units"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    syllabus_id = Column(String(36), ForeignKey("syllabi.id"), nullable=False)
    unit_number = Column(Integer, nullable=False)
    unit_title = Column(String(512), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    syllabus = relationship("Syllabus", back_populates="units")
    topics = relationship("Topic", back_populates="unit", cascade="all, delete-orphan")

class Topic(Base):
    __tablename__ = "topics"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    unit_id = Column(String(36), ForeignKey("units.id"), nullable=False)
    topic_id = Column(String(64), nullable=False, unique=True)   # CS101-U1-T1
    title = Column(String(512), nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=45)
    sequence_order = Column(Integer, nullable=True)               # where it sits in the subject's roadmap
    prerequisite_topic_id = Column(String(64), nullable=True)     # topic that should come before this one, if any
    generated_content = Column(JSON, nullable=True)               # cached lesson (llm or template), so we don't regen every visit
    generated_by = Column(String(20), nullable=True)              # ollama/mistral/groq/gemini/template - whoever made it
    explainability = Column(JSON, nullable=True)                  # how this lesson got made: provider, retrieved chunks + sources, was RAG used etc
    # learner progress, recorded by POST /topics/{id}/complete. the frontend
    # also keeps this in localStorage for instant rendering, but that's a
    # per-browser cache - these two columns are the durable copy, so progress
    # survives a cleared cache, a different browser, or a page served from
    # somewhere else. /jobs/{id} reads them back into the subject tree.
    completed_at = Column(DateTime, nullable=True)
    last_accuracy = Column(Integer, nullable=True)                # 0-100, from the most recent completion
    created_at = Column(DateTime, default=datetime.utcnow)

    unit = relationship("Unit", back_populates="topics")
    subtopics = relationship(
        "Subtopic", back_populates="topic", cascade="all, delete-orphan",
        order_by="Subtopic.order_index",
    )

class Subtopic(Base):
    # a topic's actual content is broken into these - one row per subtopic,
    # a real parent/child relationship via topic_id (FK), not just a JSON
    # array buried inside Topic.generated_content. lets each subtopic have
    # its own stable id, be queried/linked to directly, and be regenerated
    # independently of the rest of the topic if needed later.
    __tablename__ = "subtopics"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    topic_id = Column(String(36), ForeignKey("topics.id"), nullable=False)
    subtopic_id = Column(String(96), nullable=False, unique=True)   # CS101-U1-T1-S1
    order_index = Column(Integer, nullable=False, default=1)         # position within the topic
    title = Column(String(512), nullable=False)
    body = Column(Text, nullable=True)                                # the actual explanation
    source = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    topic = relationship("Topic", back_populates="subtopics")

class ReferenceSource(Base):
    # extra source docs someone uploads per subject (e.g. a textbook chapter,
    # lecture notes) - separate from the main syllabus file, just for
    # grounding lesson generation with better material. capped at 2 per
    # subject in the endpoint that creates these, not enforced here
    __tablename__ = "reference_sources"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    syllabus_id = Column(String(36), ForeignKey("syllabi.id"), nullable=False)
    subject_id = Column(String(64), nullable=False)   # e.g. "CS101" - not a FK, subjects live inside curriculum json
    original_filename = Column(String(512), nullable=False)
    stored_path = Column(String(1024), nullable=False)
    chunks_ingested = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)