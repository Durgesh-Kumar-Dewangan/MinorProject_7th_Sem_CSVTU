import os
import uuid
from datetime import datetime
from typing import Any, Optional

import aiofiles
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import models
from app.db.session import get_db
from app.schemas.syllabus import SyllabusOut
from app.services.ocr import extract_text_from_file
from app.services.parser import parse_syllabus_text
from app.services.llm_client import generate_topic_lesson
from app.services.rag_pipeline import run_topic_pipeline
from app.services.image_lookup import find_topic_image

router = APIRouter()
settings = get_settings()

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".txt"}


def _get_file_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in {".png", ".jpg", ".jpeg"}:
        return "image"
    if ext == ".txt":
        return "text"
    return "unknown"


def _topic_progress(syllabus: models.Syllabus, db: Session) -> dict[str, dict[str, Any]]:
    """topic_id -> {completed, accuracy} from the durable Topic rows.

    The frontend keeps its own copy in localStorage for instant rendering;
    this is what lets a cleared cache (or a different browser) still show the
    learner's real progress, because store.js merges whatever the backend
    reports with whatever it has locally.
    """
    rows = (
        db.query(models.Topic.topic_id, models.Topic.completed_at, models.Topic.last_accuracy)
        .join(models.Unit)
        .filter(models.Unit.syllabus_id == syllabus.id)
        .all()
    )
    return {
        r.topic_id: {"completed": r.completed_at is not None, "accuracy": r.last_accuracy}
        for r in rows
    }


def _curriculum_to_subjects(
    curriculum: dict[str, Any] | None,
    progress: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not curriculum:
        return []
    progress = progress or {}

    curriculum_block = curriculum.get("curriculum", {}) if isinstance(curriculum, dict) else {}
    subjects = curriculum_block.get("subjects", []) if isinstance(curriculum_block, dict) else []

    output: list[dict[str, Any]] = []
    for subject_index, subject in enumerate(subjects, start=1):
        subject_id = str(subject.get("subject_id") or f"sub_{subject_index}")
        subject_title = str(subject.get("subject_title") or f"Subject {subject_index}")
        units = []
        for unit_index, unit in enumerate(subject.get("units", []), start=1):
            unit_number = int(unit.get("unit_number") or unit_index)
            unit_title = str(unit.get("unit_title") or f"Unit {unit_number}")
            topics = []
            for topic_index, topic in enumerate(unit.get("topics", []), start=1):
                topic_id = str(topic.get("topic_id") or f"{subject_id}-U{unit_number}-T{topic_index}")
                topic_title = str(topic.get("title") or f"Topic {topic_index}")
                done = progress.get(topic_id) or {}
                topics.append(
                    {
                        "id": topic_id,
                        "name": topic_title,
                        "blocks": [],
                        "completed": bool(done.get("completed")),
                        "accuracy": done.get("accuracy"),
                        "status": "pending",
                    }
                )
            units.append(
                {
                    "id": f"{subject_id}-U{unit_number}",
                    "number": unit_number,
                    "name": unit_title,
                    "topics": topics,
                }
            )
        output.append({"id": subject_id, "name": subject_title, "units": units})
    return output


def _job_snapshot(syllabus: models.Syllabus, db: Session) -> dict[str, Any]:
    progress = _topic_progress(syllabus, db)
    if syllabus.status == "failed":
        return {
            "status": "error",
            "phase": syllabus.phase or "extract",
            "progress": 100,
            "subjects": _curriculum_to_subjects(syllabus.curriculum, progress),
            "error": syllabus.error_message or "Syllabus processing failed",
        }

    if syllabus.status == "parsed":
        return {
            "status": "done",
            "phase": "done",
            "progress": 100,
            "subjects": _curriculum_to_subjects(syllabus.curriculum, progress),
            "error": None,
        }

    # Still running — report real progress through extract -> distribute ->
    # generate, matching the frontend's ORDER = ["extract","distribute","generate","done"]
    # (see nsya-frontend/js/screens/extracting.js). Previously the backend
    # only ever reported "extract" or "generate" and never "distribute", so
    # that step in the UI never lit up even though the syllabus really was
    # being distributed into subjects/units/topics.
    phase = syllabus.phase or "extract"
    progress_by_phase = {"extract": 25, "distribute": 55, "generate": 80}
    return {
        "status": "running",
        "phase": phase,
        "progress": progress_by_phase.get(phase, 10),
        "subjects": _curriculum_to_subjects(syllabus.curriculum, progress),
        "error": None,
    }


def _template_topic_content(
    topic: models.Topic,
    prerequisite_title: Optional[str],
    sequence_order: Optional[int],
    subject_title: str = "",
    evidence_chunks: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    # backup generator when no llm is set up / all of them failed. every
    # topic gets its own multi-block explanation built from what we
    # actually, honestly know about it (its title, unit, subject,
    # prerequisite, position in the learning path) - not fabricated facts
    # about the topic itself, since a plain template has no real subject
    # knowledge to draw on. real per-topic output, genuinely different for
    # every topic, just not written by an actual LLM.
    topic_title = topic.title or "Topic"
    unit_title = topic.unit.unit_title if topic.unit else "Unit"
    subject_part = f" of {subject_title}" if subject_title else ""

    blocks = [
        {
            "id": f"block-{topic.id}-1",
            "title": "What this topic covers",
            "body": (
                f"{topic_title} is one of the topics in {unit_title}{subject_part}. "
                f"It's been identified as a distinct learning target in the uploaded syllabus, "
                f"separate from the other topics around it in {unit_title} — the goal here is to "
                f"understand {topic_title} specifically, well enough to explain it in your own words "
                f"before moving on."
            ),
            "source": "Generated from the uploaded syllabus outline (template)",
        },
    ]

    connect_body = ""
    if prerequisite_title:
        connect_body += (
            f"This topic comes right after {prerequisite_title} in the recommended order — "
            f"the syllabus structure suggests {prerequisite_title} lays groundwork that {topic_title} "
            f"builds on. If anything about {topic_title} feels disconnected, it's worth briefly "
            f"revisiting {prerequisite_title} first. "
        )
    else:
        connect_body += (
            f"This is an entry point — nothing earlier in {unit_title} is marked as a prerequisite "
            f"for it, so it's a reasonable place to start if you're new to this material. "
        )
    if sequence_order:
        connect_body += f"It's step {sequence_order} in {subject_title or 'this subject'}'s overall learning path."
    blocks.append({
        "id": f"block-{topic.id}-2",
        "title": "Where it fits",
        "body": connect_body.strip(),
        "source": "Derived from the syllabus's knowledge graph (unit/topic ordering, prerequisites)",
    })

    blocks.append({
        "id": f"block-{topic.id}-3",
        "title": "How to work through it",
        "body": (
            f"Read {topic_title} in the original syllabus material if you have it alongside this — "
            f"this generated overview is a scaffold, not a replacement for the source text. Then use "
            f"the quiz, arrange, fill-in, and catch exercises below to actually test whether you can "
            f"recall and apply {topic_title} without looking anything up, not just recognize it."
        ),
        "source": "Study guidance",
    })

    blocks.append({
        "id": f"block-{topic.id}-4",
        "title": "A note on this explanation",
        "body": (
            f"This particular breakdown of {topic_title} covers its structural context — what it is "
            f"in relation to {unit_title}, what comes before it, and how to approach it — because "
            f"that's what can be stated honestly without a configured AI provider. A genuine "
            f"subtopic-by-subtopic explanation of {topic_title}'s actual content requires a real "
            f"language model (see the README for free options); without one, this template "
            f"intentionally avoids inventing specific facts about {topic_title} it can't verify."
        ),
        "source": "System note",
    })

    # everything above is structural scaffolding: it makes no claims about the
    # subject itself, so the Phase 5 validators skip it (see validation.py).
    for b in blocks:
        b["scaffold"] = True

    # with retrieved evidence (the learner's own uploaded material), the
    # template can still give real content: sentences extracted VERBATIM from
    # that evidence, never paraphrased or invented. Verbatim => faithful by
    # construction, and the source is named.
    from app.services.rag_pipeline import extract_evidence_sentences

    extract = extract_evidence_sentences(topic_title, evidence_chunks or [])
    if extract:
        blocks.insert(1, {
            "id": f"block-{topic.id}-evidence",
            "title": "From your material",
            "body": " ".join(extract["sentences"]),
            "source": "Extracted verbatim from: " + ", ".join(extract["sources"]),
        })

    notes = [
        f"Review the concept of {topic_title} before moving into the next activity.",
        f"Keep {unit_title} in view while you complete the exercises.",
    ]
    if prerequisite_title:
        notes.insert(0, f"Prerequisite: {prerequisite_title} — the knowledge graph places this topic right after it.")
    if sequence_order:
        notes.append(f"This is step {sequence_order} in the recommended learning path for this subject.")

    return {
        "blocks": blocks,
        "quiz": [
            {
                "q": f"Which of the following best describes {topic_title}?",
                "options": ["A focused learning objective", "A random file name", "A database record"],
                "answer": 0,
            }
        ],
        "arrange": [
            {
                "term": topic_title,
                "keywords": [topic_title.lower().split()[0] if topic_title else "concept"],
                "distractors": ["outline", "practice"],
                "definition": f"{topic_title} represents a discrete learning target inside the broader {unit_title} sequence.",
            }
        ],
        "fill": [
            {
                "text": f"{topic_title} is a discrete learning target in the ___ sequence.",
                "answers": ["unit"],
                "bank": ["unit", "lesson", "topic", "chapter"],
            }
        ],
        "catch": [
            {"term": topic_title, "ok": True},
            {"term": "Reading focus", "ok": False},
        ],
        "notes": notes,
        "_generated_by": "template",
    }


def _find_subject_title(topic: models.Topic) -> str:
    # figures out which subject a topic actually belongs to, by matching
    # subject_id pulled from the topic_id prefix (e.g. "P101-U1-T1" -> "P101").
    # only falls back to subjects[0] if that lookup fails - just grabbing
    # subjects[0] always was a bug we had before, gave the wrong subject name
    # for anything not in the first subject of a multi-subject upload
    if not (topic.unit and topic.unit.syllabus and topic.unit.syllabus.curriculum):
        return ""
    subjects = topic.unit.syllabus.curriculum.get("curriculum", {}).get("subjects", [])
    if not subjects:
        return ""
    subject_id = topic.topic_id.split("-U")[0] if topic.topic_id else None
    for subj in subjects:
        if subj.get("subject_id") == subject_id:
            return subj.get("subject_title", "")
    return subjects[0].get("subject_title", "")


import threading

# one lock per topic_id so two things generating the same topic at the same
# time (e.g. a background pre-gen task + someone opening that exact page)
# don't both fire a real llm call. second one just waits, then sees the
# first one already finished and skips its own call.
_generation_locks: dict[str, threading.Lock] = {}
_generation_locks_guard = threading.Lock()


def _get_topic_lock(topic_id: str) -> threading.Lock:
    with _generation_locks_guard:
        lock = _generation_locks.get(topic_id)
        if lock is None:
            lock = threading.Lock()
            _generation_locks[topic_id] = lock
        return lock


def _ensure_topic_generated(topic: models.Topic, db: Session, force: bool = False) -> None:
    # generates + caches a topic's lesson (its subtopics as real Subtopic
    # rows, plus quiz/arrange/fill/catch/notes/image as JSON on the topic
    # itself) if it doesn't have one yet. no-op if it's already generated,
    # UNLESS force=True (used by the "New round" regenerate flow - see
    # get_topic_content below), which bypasses the cache entirely, deletes
    # any existing subtopics, and produces genuinely new content. safe to
    # call ahead of time (pre-gen). pulled this out on its own so the GET
    # endpoint, the pipeline's pre-gen step, and the "gen the next topic on
    # complete" step all use the same code instead of three copies that
    # could drift apart
    already_generated = bool(topic.generated_content) and len(topic.subtopics) > 0
    if already_generated and not force:
        return  # already done, and a fresh regen wasn't requested

    lock = _get_topic_lock(topic.topic_id)
    with lock:
        # someone else might've generated + committed this exact topic
        # while we were waiting on the lock above -- pull the latest state
        # from the db and bail out if so (unless force=True), otherwise
        # this would still be a second, wasted llm call
        db.refresh(topic)
        if bool(topic.generated_content) and len(topic.subtopics) > 0 and not force:
            return

        topic_title = topic.title or "Topic"
        unit_title = topic.unit.unit_title if topic.unit else "Unit"
        subject_title = _find_subject_title(topic)

        prerequisite_title = None
        if topic.prerequisite_topic_id:
            prereq_row = (
                db.query(models.Topic)
                .filter(models.Topic.topic_id == topic.prerequisite_topic_id)
                .first()
            )
            if prereq_row:
                prerequisite_title = prereq_row.title

        raw_text = (topic.unit.syllabus.raw_text or "") if topic.unit and topic.unit.syllabus else ""
        subject_id = topic.topic_id.split("-U")[0] if topic.topic_id else None

        # Phases 2-5 of the methodology (retrieval -> generation -> XAI ->
        # validation) run as one pipeline; see services/rag_pipeline.py.
        # `generate` is looked up here at call time so tests can monkeypatch it.
        body, explainability = run_topic_pipeline(
            topic_title=topic_title,
            unit_title=unit_title,
            subject_title=subject_title,
            prerequisite_title=prerequisite_title,
            sequence_order=topic.sequence_order,
            raw_text=raw_text,
            subject_id=subject_id,
            generate=generate_topic_lesson,
            template=lambda chunks: _template_topic_content(
                topic, prerequisite_title, topic.sequence_order, subject_title, evidence_chunks=chunks
            ),
        )

        # --- subtopics: real rows, not a JSON array. on regenerate, wipe
        # the old ones first so we don't end up with duplicates from a
        # previous generation sitting alongside the fresh ones.
        if force and topic.subtopics:
            for old in list(topic.subtopics):
                db.delete(old)
            db.flush()

        blocks = body.get("blocks") or []
        for i, block in enumerate(blocks, start=1):
            db.add(models.Subtopic(
                topic_id=topic.id,
                subtopic_id=f"{topic.topic_id}-S{i}",
                order_index=i,
                title=block.get("title") or f"Subtopic {i}",
                body=block.get("body") or "",
                source=block.get("source"),
            ))

        # --- image: resolved synchronously, right now, as part of
        # generation - not a separate lazy endpoint the frontend polls.
        # this means there's no loading/placeholder state to show: by the
        # time this topic's content is returned, we already know for
        # certain whether a valid image exists. if none is found, the
        # "image" key is left out of generated_content entirely (not set
        # to null, not an empty object) so the frontend has nothing to
        # branch on except "is this key present" - no broken/empty block.
        image_query = f"{topic_title} {unit_title} diagram".strip()
        image = find_topic_image(image_query)
        if not image:
            image = find_topic_image(f"{topic_title} diagram")

        generated_content = {
            "quiz": body["quiz"],
            "arrange": body["arrange"],
            "fill": body["fill"],
            "catch": body["catch"],
            "notes": body["notes"],
        }
        if image:
            generated_content["image"] = image

        topic.generated_content = generated_content
        topic.generated_by = body.get("_generated_by", "template")

        topic.explainability = explainability
        db.commit()


def _topic_content(topic: models.Topic, db: Session, force_fresh: bool = False) -> dict[str, Any]:
    prerequisite_title = None
    if topic.prerequisite_topic_id:
        prereq_row = (
            db.query(models.Topic)
            .filter(models.Topic.topic_id == topic.prerequisite_topic_id)
            .first()
        )
        if prereq_row:
            prerequisite_title = prereq_row.title

    _ensure_topic_generated(topic, db, force=force_fresh)
    body = topic.generated_content

    return {
        "status": "ready",
        "prerequisite_topic_id": topic.prerequisite_topic_id,
        "prerequisite_title": prerequisite_title,
        "sequence_order": topic.sequence_order,
        "generated_by": topic.generated_by or "template",
        "blocks": [
            {"id": s.subtopic_id, "title": s.title, "body": s.body, "source": s.source}
            for s in sorted(topic.subtopics, key=lambda s: s.order_index)
        ],
        "quiz": body["quiz"],
        "arrange": body["arrange"],
        "fill": body["fill"],
        "catch": body["catch"],
        "notes": body["notes"],
        # only present when a real image was actually found during
        # generation - never a placeholder/loading/broken entry. frontend
        # should treat "key absent" as "render nothing", not "show empty state"
        **({"image": body["image"]} if body.get("image") else {}),
    }


@router.post("/syllabus/upload")
async def upload_syllabus(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type. Allowed: {ALLOWED_EXTENSIONS}")

    file_id = str(uuid.uuid4())
    stored_name = f"{file_id}{ext}"
    stored_path = os.path.join(settings.UPLOAD_DIR, stored_name)

    async with aiofiles.open(stored_path, "wb") as out:
        content = await file.read()
        await out.write(content)

    syllabus = models.Syllabus(
        original_filename=file.filename,
        stored_path=stored_path,
        file_type=_get_file_type(file.filename),
        status="uploaded",
    )
    db.add(syllabus)
    db.commit()
    db.refresh(syllabus)

    background_tasks.add_task(process_syllabus, str(syllabus.id))

    return {"jobId": str(syllabus.id)}


def _disambiguate_subject_ids(curriculum: dict, db: Session, this_syllabus_id: str) -> None:
    # subject_id (e.g. "CS101") is derived purely from the subject's title
    # text (see parser.py::derive_subject_id) with no randomness. that's
    # fine for a single upload, but topic_id is globally unique across ALL
    # syllabi ("CS101-U1-T1"), so a second, unrelated syllabus that also
    # happens to have a "Computer Science" subject with a "Variables" topic
    # would collide with the first one's rows and crash the whole upload
    # with a database IntegrityError. found this the hard way - re-running
    # the pipeline against a database that already had a matching subject
    # id in it reproduced the crash exactly.
    #
    # fix: before creating any rows, check whether this subject_id already
    # belongs to a DIFFERENT syllabus's topics in the db. if so, rewrite it
    # (and every topic_id under it) to a disambiguated version unique to
    # this syllabus, so two uploads that happen to share subject/unit/topic
    # naming can coexist instead of crashing.
    for subj in curriculum.get("curriculum", {}).get("subjects", []):
        subject_id = subj.get("subject_id")
        if not subject_id:
            continue

        collision = (
            db.query(models.Topic)
            .join(models.Unit)
            .filter(
                models.Unit.syllabus_id != this_syllabus_id,
                models.Topic.topic_id.like(f"{subject_id}-U%"),
            )
            .first()
        )
        if not collision:
            continue

        new_subject_id = f"{subject_id}-{this_syllabus_id[:4]}"
        subj["subject_id"] = new_subject_id
        for unit in subj.get("units", []):
            for topic in unit.get("topics", []):
                old_id = topic.get("topic_id", "")
                if old_id.startswith(f"{subject_id}-U"):
                    topic["topic_id"] = new_subject_id + old_id[len(subject_id):]


def process_syllabus(syllabus_id: str):
    # background job: extract text -> parse into subject/unit/topic -> build
    # knowledge graph -> generate. matches the 4 stages the frontend progress
    # bar expects (extract -> distribute -> generate -> done, see
    # nsya-frontend/js/screens/extracting.js)
    #
    # 1. extract    - pull text out of the uploaded file
    # 2. distribute - parse into subject/unit/topic rows, then build the graph
    #                 and work out each topic's sequence_order + prerequisite.
    #                 this is the step that actually figures out how topics
    #                 relate to each other, not just listing them flat
    # 3. generate   - pre-generate the first topic of each unit so it's ready
    #                 to go. everything else generates lazily when opened
    # 4. done       - status="parsed", phase="done"
    from app.db.session import SessionLocal
    from app.services.knowledge_graph import (
        build_knowledge_graph,
        generate_roadmap,
        graph_to_dict,
        get_prerequisites,
    )

    db = SessionLocal()
    syllabus = None
    try:
        syllabus = db.query(models.Syllabus).filter(models.Syllabus.id == syllabus_id).first()
        if not syllabus:
            return

        # ---- Stage 1: extract ----
        syllabus.status = "processing"
        syllabus.phase = "extract"
        db.commit()

        raw_text = extract_text_from_file(syllabus.stored_path, syllabus.file_type)
        syllabus.raw_text = raw_text

        curriculum = parse_syllabus_text(raw_text)
        _disambiguate_subject_ids(curriculum, db, syllabus.id)
        syllabus.curriculum = curriculum
        db.commit()

        # ---- Stage 2: distribute (normalize rows + build knowledge graph) ----
        syllabus.phase = "distribute"
        db.commit()

        topics_by_topic_id: dict[str, models.Topic] = {}
        for subj in curriculum.get("curriculum", {}).get("subjects", []):
            for unit_data in subj.get("units", []):
                unit = models.Unit(
                    syllabus_id=syllabus.id,
                    unit_number=unit_data["unit_number"],
                    unit_title=unit_data["unit_title"],
                )
                db.add(unit)
                db.flush()
                for topic_data in unit_data.get("topics", []):
                    topic = models.Topic(
                        unit_id=unit.id,
                        topic_id=topic_data["topic_id"],
                        title=topic_data["title"],
                        duration_minutes=topic_data["duration_minutes"],
                    )
                    db.add(topic)
                    db.flush()
                    topics_by_topic_id[topic.topic_id] = topic

        # Build the knowledge graph over the whole curriculum (all subjects),
        # store it so /api/v1/knowledge endpoints and future requests don't
        # need to rebuild it, then use it to compute each topic's place in
        # its subject's learning roadmap and its direct prerequisite.
        graph = build_knowledge_graph(curriculum)
        syllabus.knowledge_graph = graph_to_dict(graph)

        for subj in curriculum.get("curriculum", {}).get("subjects", []):
            subject_id = subj["subject_id"]
            roadmap = generate_roadmap(graph, subject_id)
            order = 0
            for step in roadmap:
                if step.get("type") != "topic":
                    continue
                order += 1
                topic_row = topics_by_topic_id.get(step["node_key"])
                if not topic_row:
                    continue
                topic_row.sequence_order = order
                prereqs = [
                    p for p in get_prerequisites(graph, step["node_key"])
                    if graph.nodes[p].get("type") == "topic"
                ]
                topic_row.prerequisite_topic_id = prereqs[0] if prereqs else None

        db.commit()

        # ---- RAG ingestion: index the syllabus text for retrieval ----
        # For each subject, chunk-and-embed the syllabus's raw extracted
        # text into that subject's FAISS index (see
        # app/services/embeddings.py), so lesson generation can retrieve
        # the most relevant passages for a specific topic instead of
        # blindly truncating the whole document. This is genuinely optional
        # at the dependency level: if faiss/sentence-transformers aren't
        # installed, this whole block is skipped silently and generation
        # falls back to naive excerpt-based context — nothing here can fail
        # the pipeline.
        try:
            from app.services.embeddings import ingest_document_for_topic
            for subj in curriculum.get("curriculum", {}).get("subjects", []):
                ingest_document_for_topic(
                    subject_id=subj["subject_id"],
                    topic_id="syllabus-source",
                    document_text=raw_text,
                    source=syllabus.original_filename,
                )
        except Exception:
            pass

        # ---- Stage 3: generate ----
        # Full lesson content is still generated lazily per-topic on first
        # visit (see get_topic_content below) — but if
        # PREGENERATE_UNIT_ENTRY_TOPICS is on (default), the *first* topic
        # of every unit gets generated right now, before the pipeline even
        # finishes, so a learner opening any unit for the first time never
        # has to wait on a live LLM call for the topic they're most likely
        # to open first. Every other topic in the unit is still generated
        # on demand, keeping this a real cost/latency tradeoff rather than
        # a "generate everything up front" approach that would burn free
        # API quota on topics that might never be opened.
        syllabus.phase = "generate"
        db.commit()

        if settings.PREGENERATE_UNIT_ENTRY_TOPICS and not settings.PREGENERATE_ALL_TOPICS:
            first_topic_by_unit: dict[str, models.Topic] = {}
            for topic_row in topics_by_topic_id.values():
                existing = first_topic_by_unit.get(topic_row.unit_id)
                if existing is None or (topic_row.sequence_order or 0) < (existing.sequence_order or 0):
                    first_topic_by_unit[topic_row.unit_id] = topic_row
            for topic_row in first_topic_by_unit.values():
                try:
                    _ensure_topic_generated(topic_row, db)
                except Exception:
                    # A single provider/network hiccup pre-generating one
                    # unit's entry topic shouldn't fail the whole upload —
                    # that topic just falls back to lazy on-demand
                    # generation the first time it's actually opened.
                    pass

        # every topic in every unit, right now — opt-in, see the cost note
        # on PREGENERATE_ALL_TOPICS in config.py. same per-topic try/except
        # as above: one topic failing to generate shouldn't take the whole
        # upload down with it, it just falls back to on-demand later.
        elif settings.PREGENERATE_ALL_TOPICS:
            for topic_row in topics_by_topic_id.values():
                try:
                    _ensure_topic_generated(topic_row, db)
                except Exception:
                    pass

        # ---- Stage 4: done ----
        syllabus.status = "parsed"
        syllabus.phase = "done"
        db.commit()
    except Exception as e:
        # if the original failure came from a db-level error (like a flush
        # or commit failing), the session is left in a "pending rollback"
        # state - trying to commit again here without rolling back first
        # would itself raise, meaning the syllabus never actually gets
        # marked "failed" and just stays stuck on "processing" forever with
        # no error message ever recorded. roll back first so this handler
        # can actually do its job.
        db.rollback()
        if syllabus is not None:
            syllabus.status = "failed"
            syllabus.phase = "error"
            syllabus.error_message = str(e)[:1000]
            db.commit()
    finally:
        db.close()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    syllabus = db.query(models.Syllabus).filter(models.Syllabus.id == job_id).first()
    if not syllabus:
        raise HTTPException(404, "Job not found")
    return _job_snapshot(syllabus, db)


@router.get("/topics/{topic_id}")
def get_topic_content(topic_id: str, regenerate: bool = False, db: Session = Depends(get_db)):
    topic = (
        db.query(models.Topic)
        .filter(models.Topic.topic_id == topic_id)
        .first()
    )
    if not topic:
        # Fallback: topic not yet persisted (e.g. content requested before the
        # background parse finished writing rows) — still return something
        # renderable instead of a hard 404 so the frontend never gets stuck.
        title = topic_id.replace("-", " ")
        return {
            "status": "ready",
            "blocks": [
                {
                    "id": f"{topic_id}-b1",
                    "title": "Topic Overview",
                    "body": f"This topic is currently mapped as {title}. Use the exercises below as a lightweight starter view while the full lesson pipeline is connected.",
                    "source": "Local SYA fallback",
                }
            ],
            "quiz": [
                {
                    "q": f"What is the main focus of {title}?",
                    "options": ["Concept recall", "Topic exploration", "Text generation", "None of the above"],
                    "answer": 1,
                }
            ],
            "arrange": [],
            "fill": [],
            "catch": [
                {"term": title, "ok": True},
                {"term": "General review", "ok": False},
            ],
            "notes": [f"Topic {topic_id} is ready for learning."],
        }

    # regenerate=true (only sent by the frontend's explicit "New round"
    # button, never on a normal page load) forces a genuinely fresh
    # generation call, bypassing the cache. normal visits still use the
    # cache as before -- this is deliberately opt-in per request, not a
    # global "never cache" change, so ordinary navigation doesn't quietly
    # start burning an LLM call on every single visit.
    return _topic_content(topic, db, force_fresh=regenerate)


@router.get("/topics/{topic_id}/subtopics")
def list_subtopics(topic_id: str, db: Session = Depends(get_db)):
    # small child-node list for the given topic - id/title/order only, not
    # the full body text, so a "parent node with subtopic children" UI can
    # render quickly without pulling every subtopic's full explanation
    topic = db.query(models.Topic).filter(models.Topic.topic_id == topic_id).first()
    if not topic:
        raise HTTPException(404, "Topic not found")

    _ensure_topic_generated(topic, db)

    return {
        "topic_id": topic.topic_id,
        "topic_title": topic.title,
        "subtopics": [
            {"id": s.subtopic_id, "title": s.title, "order": s.order_index}
            for s in sorted(topic.subtopics, key=lambda s: s.order_index)
        ],
    }


@router.get("/subtopics/{subtopic_id}")
def get_subtopic_content(subtopic_id: str, db: Session = Depends(get_db)):
    # a single subtopic's own learning session - full explanation, plus
    # enough context (parent topic/unit/subject) to know what it belongs to
    subtopic = db.query(models.Subtopic).filter(models.Subtopic.subtopic_id == subtopic_id).first()
    if not subtopic:
        raise HTTPException(404, "Subtopic not found")

    topic = subtopic.topic
    unit_title = topic.unit.unit_title if topic and topic.unit else None
    subject_title = _find_subject_title(topic) if topic else None

    return {
        "subtopic_id": subtopic.subtopic_id,
        "title": subtopic.title,
        "body": subtopic.body,
        "source": subtopic.source,
        "order": subtopic.order_index,
        "topic_id": topic.topic_id if topic else None,
        "topic_title": topic.title if topic else None,
        "unit_title": unit_title,
        "subject_title": subject_title,
    }


def _resolve_source_url(source_label: str, topic: models.Topic, db: Session) -> Optional[str]:
    # retrieved_chunks store a human-readable "source" label (either the
    # main syllabus's original filename, or "reference:<filename>" for an
    # uploaded reference doc) - not a stored path. resolves that label back
    # to a real, clickable URL under the /uploads static mount (see
    # main.py), so the explainability panel can link to the actual source
    # document instead of just naming it.
    if not source_label or not topic.unit or not topic.unit.syllabus:
        return None

    syllabus = topic.unit.syllabus
    if source_label == syllabus.original_filename:
        return f"/uploads/{os.path.basename(syllabus.stored_path)}"

    if source_label.startswith("reference:"):
        filename = source_label[len("reference:"):]
        subject_id = topic.topic_id.split("-U")[0] if topic.topic_id else None
        ref = (
            db.query(models.ReferenceSource)
            .filter(models.ReferenceSource.subject_id == subject_id, models.ReferenceSource.original_filename == filename)
            .first()
        )
        if ref:
            return f"/uploads/{os.path.basename(ref.stored_path)}"

    return None


@router.get("/topics/{topic_id}/explainability")
def get_topic_explainability(topic_id: str, db: Session = Depends(get_db)):
    # xai panel data - shows how a lesson actually got made: which provider
    # wrote it, whether rag kicked in, and which chunks of which source doc
    # it pulled from. purely informational, doesn't touch the lesson itself.
    # generates the topic first if it hasn't been yet, so this always has
    # something to show instead of an empty response
    topic = (
        db.query(models.Topic)
        .filter(models.Topic.topic_id == topic_id)
        .first()
    )
    if not topic:
        return {"available": False}

    if not topic.explainability:
        _ensure_topic_generated(topic, db)

    if not topic.explainability:
        return {"available": False}

    result = {"available": True, **topic.explainability}
    # attach a real, clickable URL to each retrieved chunk where one can be
    # resolved - never fails the whole response if a source can't be found
    # (e.g. the file was since deleted), that chunk's info just has no link
    chunks = result.get("retrieved_chunks") or []
    result["retrieved_chunks"] = [
        {**c, "source_url": _resolve_source_url(c.get("source", ""), topic, db)}
        for c in chunks
    ]
    return result


MAX_REFERENCE_SOURCES_PER_SUBJECT = 2


@router.post("/subjects/{subject_id}/sources")
async def upload_reference_source(
    subject_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # lets someone upload 1-2 extra reference docs per subject (a textbook
    # chapter, notes, whatever) on top of the main syllabus, purely to give
    # generation better material to pull from. capped at
    # MAX_REFERENCE_SOURCES_PER_SUBJECT - doesn't touch the learning flow at
    # all, this is an optional side door
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    existing_count = (
        db.query(models.ReferenceSource)
        .filter(models.ReferenceSource.subject_id == subject_id)
        .count()
    )
    if existing_count >= MAX_REFERENCE_SOURCES_PER_SUBJECT:
        raise HTTPException(
            400,
            f"Already have {existing_count} reference sources for this subject "
            f"(max {MAX_REFERENCE_SOURCES_PER_SUBJECT}). Delete one first if you want to add another.",
        )

    # need a syllabus row to hang this off of - just grab any syllabus that
    # actually contains this subject_id (via its topics), since subjects
    # aren't their own table
    unit_row = (
        db.query(models.Unit)
        .join(models.Topic)
        .filter(models.Topic.topic_id.like(f"{subject_id}-U%"))
        .first()
    )
    if not unit_row:
        raise HTTPException(404, f"No subject found with id {subject_id}")
    syllabus_id = unit_row.syllabus_id

    ext = os.path.splitext(file.filename)[1].lower()
    file_type = "pdf" if ext == ".pdf" else ("image" if ext in (".png", ".jpg", ".jpeg") else "text")
    dest_path = os.path.join(settings.UPLOAD_DIR, f"ref-{uuid.uuid4()}{ext}")
    async with aiofiles.open(dest_path, "wb") as f:
        await f.write(await file.read())

    text = extract_text_from_file(dest_path, file_type)

    chunks_added = 0
    try:
        from app.services.embeddings import ingest_document_for_topic
        chunks_added = ingest_document_for_topic(
            subject_id=subject_id,
            topic_id="reference-source",
            document_text=text,
            source=f"reference:{file.filename}",
        )
    except Exception:
        pass  # faiss/sentence-transformers not installed - doc is saved but won't be searchable until it is

    ref = models.ReferenceSource(
        syllabus_id=syllabus_id,
        subject_id=subject_id,
        original_filename=file.filename,
        stored_path=dest_path,
        chunks_ingested=chunks_added,
    )
    db.add(ref)
    db.commit()
    db.refresh(ref)

    return {
        "id": ref.id,
        "filename": ref.original_filename,
        "chunks_ingested": ref.chunks_ingested,
    }


@router.get("/subjects/{subject_id}/sources")
def list_reference_sources(subject_id: str, db: Session = Depends(get_db)):
    # for the small corner "sources" indicator - just lists what's been
    # uploaded for this subject so far
    rows = (
        db.query(models.ReferenceSource)
        .filter(models.ReferenceSource.subject_id == subject_id)
        .order_by(models.ReferenceSource.created_at.desc())
        .all()
    )
    return {
        "subject_id": subject_id,
        "count": len(rows),
        "max": MAX_REFERENCE_SOURCES_PER_SUBJECT,
        "sources": [
            {"id": r.id, "filename": r.original_filename, "chunks_ingested": r.chunks_ingested}
            for r in rows
        ],
    }


@router.post("/topics/{topic_id}/complete")
def complete_topic(
    topic_id: str,
    background_tasks: BackgroundTasks,
    payload: dict | None = None,
    db: Session = Depends(get_db),
):
    payload = payload or {}
    topic = (
        db.query(models.Topic)
        .filter(models.Topic.topic_id == topic_id)
        .first()
    )
    if topic:
        # Record the completion durably. This used to only touch
        # duration_minutes (a no-op write) and throw the accuracy away, so
        # progress lived exclusively in the browser's localStorage and was
        # lost on a cache clear or a different browser. /jobs/{id} reads
        # these back, and store.js merges them with whatever local progress
        # the browser already has.
        accuracy = payload.get("accuracy")
        if isinstance(accuracy, (int, float)) and not isinstance(accuracy, bool):
            topic.last_accuracy = max(0, min(100, int(round(accuracy))))
        topic.completed_at = datetime.utcnow()
        db.commit()

        # Generate the *next* topic in this subject's learning path now, in
        # the background, so it's already cached by the time the learner
        # navigates to it instead of making them wait on a live LLM call
        # right after they just finished the previous one. Only fires if
        # there IS a next topic and it isn't already generated — otherwise
        # a no-op.
        if settings.PREGENERATE_NEXT_ON_COMPLETE and topic.sequence_order is not None:
            subject_id = topic_id.split("-U")[0] if topic_id else None
            next_topic = (
                db.query(models.Topic)
                .join(models.Unit)
                .filter(
                    models.Unit.syllabus_id == topic.unit.syllabus_id,
                    models.Topic.sequence_order == topic.sequence_order + 1,
                    models.Topic.topic_id.like(f"{subject_id}-U%"),
                )
                .first()
            )
            if next_topic and not next_topic.generated_content:
                background_tasks.add_task(_generate_topic_in_background, next_topic.id)

    return {
        "ok": True,
        "topic_id": topic_id,
        # echo back what was actually STORED (clamped to 0-100, or null
        # if the payload had no usable number), not the raw input
        "accuracy": topic.last_accuracy if topic else payload.get("accuracy"),
        "recorded": topic is not None,
    }


def _generate_topic_in_background(topic_row_id: str):
    # runs after the /complete response already went out, so needs its own
    # db session - the request-scoped one from complete_topic() is closed
    # by the time this actually fires
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        topic = db.query(models.Topic).filter(models.Topic.id == topic_row_id).first()
        if topic:
            _ensure_topic_generated(topic, db)
    except Exception:
        pass  # next topic just falls back to lazy on-demand generation on first visit
    finally:
        db.close()


@router.get("/", response_model=list[SyllabusOut])
def list_syllabi(db: Session = Depends(get_db)):
    return db.query(models.Syllabus).order_by(models.Syllabus.created_at.desc()).all()


@router.get("/{syllabus_id}", response_model=SyllabusOut)
def get_syllabus(syllabus_id: str, db: Session = Depends(get_db)):
    syllabus = db.query(models.Syllabus).filter(models.Syllabus.id == syllabus_id).first()
    if not syllabus:
        raise HTTPException(404, "Syllabus not found")
    return syllabus
