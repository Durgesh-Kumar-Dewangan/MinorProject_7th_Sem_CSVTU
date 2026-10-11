import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine
from app.api.routers import knowledge, syllabus

settings = get_settings()
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

Base.metadata.create_all(bind=engine)


def _add_missing_columns() -> None:
    """Additive schema catch-up for databases created by an older version.

    create_all() only ever CREATEs missing tables - it never ALTERs an
    existing one. So a column added to a model after someone already has a
    sya.db simply doesn't exist in their file, and every query touching it
    fails with "no such column". There's no Alembic in the default install
    (it's an optional extra in requirements.txt), so this does the one thing
    that's actually needed: ADD COLUMN for model columns the live table is
    missing. Nullable adds only - it never drops, renames or retypes
    anything, so it cannot lose data, and it's a no-op on a fresh database.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all already made it, with every column
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                if not column.nullable or column.primary_key:
                    continue  # can't backfill a NOT NULL column safely; leave it alone
                ddl = column.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}'))


_add_missing_columns()

app = FastAPI(
    title="Explainable AI Personalized Learning Platform",
    version="0.1.0",
    description="Phase 1 – Foundation + Syllabus Parsing",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# serves uploaded files (the main syllabus + any reference sources) at
# /uploads/<filename>, so the Explainable AI panel can link straight to the
# actual source document a lesson was generated from, not just name it.
# read-only, static - nothing here accepts writes.
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


# NOTE: this must be registered *before* the syllabus router below, because
# that router exposes a catch-all "/{syllabus_id}" route. Starlette matches
# routes in registration order, so if the router were included first, a
# request to "/health" would match "/{syllabus_id}" (with syllabus_id="health")
# and 404 with "Syllabus not found" instead of ever reaching this handler.
@app.get("/health")
def health():
    return {"status": "ok", "phase": 1}


app.include_router(syllabus.router, tags=["Syllabus"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["Knowledge"])
