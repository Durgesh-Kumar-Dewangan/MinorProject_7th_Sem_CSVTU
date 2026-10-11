"""
Shared pytest fixtures.

Uses the app's real SQLite database file (same engine the app itself
uses - see app/db/session.py) rather than an in-memory DB, matching the
exact pattern used for manual verification throughout this project's
development: it's the setup that's actually been proven to work, so tests
built on it should behave the same way the app does when you run it
yourself.

Each test gets a completely fresh database: the file is deleted and the
schema recreated before every test function, so nothing leaks between
tests.
"""
import gc
import os
import shutil
import time
import uuid

# Tests get their OWN database file. This must be set before app.db.session
# is imported (the engine is built at import time). Previously the fixture
# below deleted "app.db" while the app actually used "sya.db", so tests never
# got a fresh database, leaked state into each other, and (worse) could touch
# the developer's real database.
os.environ["DATABASE_URL"] = "sqlite:///./test_suite.db"

# Same reasoning for the retrieval indexes. Ingestion is keyed by
# subject_id and the fixtures use real-looking ids ("CS101"), so with the
# app's default directory the suite wrote fixture chunks straight into the
# index a developer's own running app retrieves from - every test run
# permanently mixing sample-syllabus.txt into their real lessons' evidence,
# and leaking between tests besides. Measured on a dev machine before this
# line existed: 36 fixture chunks sitting in the live CS101 index.
os.environ["FAISS_INDEX_DIR"] = "./test_faiss_indexes"

# ...and for uploaded files, for the same reason: the suite was copying
# every fixture syllabus (and every reference source an endpoint test
# uploads) straight into the app's own uploads/ directory, leaving dozens of
# orphaned files there - 72 of them on the machine where this was noticed.
os.environ["UPLOAD_DIR"] = "./test_uploads"

import pytest

from app.api.routers import syllabus as syllabus_router
from app.db import models  # noqa: F401 - must be imported before create_all so Base knows about every table
from app.db.base import Base
from app.db.session import engine, SessionLocal

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_SYLLABUS = os.path.join(os.path.dirname(BACKEND_DIR), "sample-syllabus.txt")
MULTI_SUBJECT_SYLLABUS = os.path.join(os.path.dirname(BACKEND_DIR), "multi-subject-sample.txt")


def _reset_database() -> None:
    """Delete and recreate the test database file.

    Deleting the file is the cleanest reset, but on Windows it fails with
    PermissionError (WinError 32) if ANY connection still holds the file -
    and a test that fails partway through never reaches its own
    `db.close()`, so it leaks a session. That used to turn one genuine
    failure into a cascade of unrelated ERRORs in every test that followed
    it, which hides the real problem.

    So: dispose the pool, collect whatever unreferenced sessions are still
    holding connections, retry the delete a few times, and if the file
    STILL won't go, fall back to dropping and recreating the tables through
    SQLAlchemy. The fallback leaves the same empty schema behind, so the
    next test starts clean either way and a single failure stays a single
    failure.
    """
    db_file = os.path.join(BACKEND_DIR, engine.url.database.lstrip("./"))

    engine.dispose()
    gc.collect()  # drop leaked Session objects from a failed test, freeing their connections

    for attempt in range(5):
        if not os.path.exists(db_file):
            break
        try:
            os.remove(db_file)
            break
        except PermissionError:
            engine.dispose()
            gc.collect()
            time.sleep(0.1)
    else:
        # Couldn't remove the file - reset its contents in place instead.
        Base.metadata.drop_all(bind=engine)

    Base.metadata.create_all(bind=engine)


def _reset_indexes() -> None:
    """Empty the test-only FAISS index directory.

    Without this, a subject id reused across tests (every fixture uses
    "CS101") accumulates chunks from previous tests, so retrieval results
    depend on test execution order.
    """
    from app.core.config import get_settings

    path = os.path.join(BACKEND_DIR, get_settings().FAISS_INDEX_DIR.lstrip("./"))
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def db_session():
    """A clean database + indexes, and a Session bound to the database."""
    _reset_database()
    _reset_indexes()

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def offline_image_lookup(monkeypatch):
    """Stub the Openverse image lookup out of every test by default.

    Generation calls find_topic_image() for real (twice per topic, 6s
    timeout each). That makes the suite slow and, worse,
    environment-dependent: on a machine WITH internet a real image comes
    back and any test asserting "no image" fails, while on a machine
    without it the same test passes. Neither outcome tells you anything
    about the code.

    Patched to None here, so every test sees the deterministic "no image
    found" path. Tests that care about the image behaviour set their own
    stub with monkeypatch (which overrides this one) - see
    test_generation.py::test_image_key_present_only_when_an_image_is_found.
    """
    monkeypatch.setattr(syllabus_router, "find_topic_image", lambda query: None)


@pytest.fixture()
def uploads_dir():
    """The test-only upload directory (UPLOAD_DIR, set at the top of this
    file), emptied for each test so nothing accumulates and nothing lands in
    the app's own uploads/."""
    from app.core.config import get_settings

    path = os.path.join(BACKEND_DIR, get_settings().UPLOAD_DIR.lstrip("./"))
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    return path


def upload_and_process(db_session, uploads_dir, source_path: str) -> str:
    """
    Test helper: simulates the /syllabus/upload endpoint's DB-write step
    plus the background processing task, without going through HTTP -
    the same pattern used throughout this project's manual verification.
    Returns the new syllabus's id. Does not close db_session - open a
    fresh SessionLocal() in the test itself for post-processing queries,
    the same pattern process_syllabus itself uses internally.
    """
    from app.api.routers.syllabus import process_syllabus

    dest = os.path.join(uploads_dir, f"{uuid.uuid4()}.txt")
    shutil.copy(source_path, dest)

    syllabus = models.Syllabus(
        original_filename=os.path.basename(source_path),
        stored_path=dest,
        file_type="text",
        status="uploaded",
    )
    db_session.add(syllabus)
    db_session.commit()
    db_session.refresh(syllabus)
    syllabus_id = str(syllabus.id)

    process_syllabus(syllabus_id)  # opens + closes its own session internally, same as the real background task
    return syllabus_id
