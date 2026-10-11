"""
Real LLM providers (Groq / Mistral / Gemini / Ollama), and what the trust
score actually compares.

Two things are tested here, and it's worth being precise about which:

1. The provider WIRE FORMAT. `urllib.request.urlopen` is faked, so the real
   `generate_topic_lesson` runs end to end - prompt construction, endpoint
   URL, auth header, request body, response parsing, JSON extraction,
   shape validation, provider fallback. Everything except the TLS hop to
   the real host. If Groq changes its response shape or a header, these
   fail.

2. That the Phase 4/5 report really compares the GENERATED LESSON against
   THE UPLOADED FILE'S OWN TEXT, rather than scoring something unrelated.
   A full upload runs through the real pipeline, then the same topic is
   generated twice through the fake Groq: once with a lesson that restates
   the uploaded material, once with a lesson about something else entirely.
   Every metric has to move in the right direction, and the evidence has to
   name the uploaded file.

What is NOT covered: reaching the real api.groq.com / api.mistral.ai. That
needs a key and a network, so it's the one thing only your own machine can
confirm.
"""
import json
import urllib.error
import urllib.request

import pytest

from app.core.config import get_settings
from app.db import models
from app.db.session import SessionLocal
from app.services import llm_client

# A syllabus with real explanatory prose in it, not just a list of topic
# names. This matters: the validators compare generated sentences against
# retrieved sentences, so a file that only contains "- Stacks" has nothing
# to be grounded IN, and the report correctly says so (trust_score: null)
# rather than inventing a number. Grounding needs material.
SYLLABUS = """Computer Science 101

Unit 1: Linear Data Structures
- Stacks
- Queues

Stacks are linear data structures that follow the last in first out principle.
Push adds an element to the top of the stack and pop removes the top element
from the stack.

Queues follow the first in first out principle. Enqueue adds an element at the
rear of the queue and dequeue removes the element from the front of the queue.
"""

GROUNDED_LESSON = {
    "blocks": [
        {
            "title": "Last in, first out",
            "body": "Stacks are linear data structures that follow the last in first out principle. "
                    "Push adds an element to the top of the stack. Pop removes the top element from the stack.",
            "source": "Generated explanation",
        }
    ],
    "quiz": [{"q": "A stack is…", "options": ["last in first out", "first in first out"], "answer": 0}],
    "arrange": [{"term": "Stack", "keywords": ["last", "in", "first", "out"], "distractors": ["rear"],
                 "definition": "A stack removes the most recently added element first."}],
    "fill": [{"text": "A stack follows the ___ in first out principle.", "answers": ["last"],
              "bank": ["last", "first"]}],
    "catch": [{"term": "Push", "ok": True}, {"term": "Photosynthesis", "ok": False}],
    "notes": ["Push and pop both act on the top of the stack."],
}

HALLUCINATED_LESSON = {
    "blocks": [
        {
            "title": "Stacks in marine biology",
            "body": "Blue whales migrate across oceans every winter season and feed on krill near polar regions. "
                    "A colony contains exactly 4096 individuals during the breeding period. "
                    "Their songs travel hundreds of kilometres through deep water.",
            "source": "Generated explanation",
        }
    ],
    "quiz": [{"q": "Whales eat…", "options": ["krill", "stacks"], "answer": 0}],
    "arrange": [{"term": "Whale", "keywords": ["large", "marine", "mammal"], "distractors": ["pop"],
                 "definition": "A large marine mammal."}],
    "fill": [{"text": "Whales feed on ___.", "answers": ["krill"], "bank": ["krill", "push"]}],
    "catch": [{"term": "Krill", "ok": True}, {"term": "Pop", "ok": False}],
    "notes": ["Unrelated to the uploaded syllabus."],
}


class _FakeResponse:
    """Just enough of http.client.HTTPResponse for llm_client._post_json."""

    status = 200

    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def fake_http(monkeypatch):
    """Intercepts urlopen. Returns a recorder: .requests and .responder."""

    class Recorder:
        def __init__(self):
            self.requests = []
            self.responder = lambda req: {}

    rec = Recorder()

    def fake_urlopen(req, timeout=None):
        rec.requests.append(req)
        return _FakeResponse(rec.responder(req))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return rec


@pytest.fixture()
def provider_env(monkeypatch):
    """Configure providers through real settings, and reset the cache after.

    get_settings() is lru_cached and llm_client reads it per call, so the
    cache has to be cleared on the way in AND out or the setting leaks into
    other tests.
    """

    def configure(**env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return get_settings()

    yield configure
    get_settings.cache_clear()


def _chat_completion(lesson, fenced=False):
    """A Groq/Mistral-shaped (OpenAI-compatible) chat completion."""
    content = json.dumps(lesson)
    if fenced:
        content = f"Sure, here's the lesson:\n```json\n{content}\n```"
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _generate(**overrides):
    kwargs = dict(
        topic_title="Stacks", unit_title="Linear Data Structures", subject_title="Computer Science",
        prerequisite_title=None, sequence_order=1, source_excerpt=SYLLABUS,
    )
    kwargs.update(overrides)
    return llm_client.generate_topic_lesson(**kwargs)


# --------------------------- 1. provider wire format ---------------------------

def test_groq_request_is_built_and_parsed_correctly(fake_http, provider_env):
    provider_env(LLM_PROVIDER_ORDER="groq", GROQ_API_KEY="test-key-123", GROQ_MODEL="llama-3.1-8b-instant")
    fake_http.responder = lambda req: _chat_completion(GROUNDED_LESSON)

    result = _generate()

    assert result is not None, "a valid Groq response must produce a lesson"
    assert result["_generated_by"] == "groq"
    assert result["blocks"][0]["title"] == "Last in, first out"

    assert len(fake_http.requests) == 1
    req = fake_http.requests[0]
    assert req.full_url == "https://api.groq.com/openai/v1/chat/completions"
    assert req.get_header("Authorization") == "Bearer test-key-123"
    assert req.get_header("Content-type") == "application/json"

    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == "llama-3.1-8b-instant"
    assert body["messages"][0]["role"] == "user"
    # the prompt must actually carry the topic and the learner's material
    assert "Stacks" in body["messages"][0]["content"]
    assert "last in first out" in body["messages"][0]["content"]


def test_mistral_request_is_built_and_parsed_correctly(fake_http, provider_env):
    provider_env(LLM_PROVIDER_ORDER="mistral", MISTRAL_API_KEY="mistral-key", MISTRAL_MODEL="mistral-small-latest")
    fake_http.responder = lambda req: _chat_completion(GROUNDED_LESSON)

    result = _generate()

    assert result is not None and result["_generated_by"] == "mistral"
    req = fake_http.requests[0]
    assert req.full_url == "https://api.mistral.ai/v1/chat/completions"
    assert req.get_header("Authorization") == "Bearer mistral-key"
    assert json.loads(req.data.decode("utf-8"))["model"] == "mistral-small-latest"


def test_gemini_and_ollama_shapes(fake_http, provider_env):
    provider_env(LLM_PROVIDER_ORDER="gemini", GEMINI_API_KEY="g-key", GEMINI_MODEL="gemini-1.5-flash")
    fake_http.responder = lambda req: {
        "candidates": [{"content": {"parts": [{"text": json.dumps(GROUNDED_LESSON)}]}}]
    }
    assert _generate()["_generated_by"] == "gemini"
    assert "models/gemini-1.5-flash:generateContent?key=g-key" in fake_http.requests[0].full_url

    fake_http.requests.clear()
    provider_env(LLM_PROVIDER_ORDER="ollama", OLLAMA_BASE_URL="http://localhost:11434", OLLAMA_MODEL="llama3.2")
    fake_http.responder = lambda req: {"response": json.dumps(GROUNDED_LESSON)}
    assert _generate()["_generated_by"] == "ollama"
    assert fake_http.requests[0].full_url == "http://localhost:11434/api/generate"


def test_a_provider_with_no_key_is_skipped_without_any_request(fake_http, provider_env):
    # groq has no key, mistral does -> groq must not even be called
    provider_env(LLM_PROVIDER_ORDER="groq,mistral", GROQ_API_KEY="", MISTRAL_API_KEY="mistral-key")
    fake_http.responder = lambda req: _chat_completion(GROUNDED_LESSON)

    assert _generate()["_generated_by"] == "mistral"
    assert len(fake_http.requests) == 1
    assert "mistral" in fake_http.requests[0].full_url


def test_order_is_honoured_and_a_bad_response_falls_through(fake_http, provider_env):
    provider_env(LLM_PROVIDER_ORDER="groq,mistral", GROQ_API_KEY="g", MISTRAL_API_KEY="m")

    def responder(req):
        # groq answers with prose instead of JSON -> unusable, must fall through
        if "groq" in req.full_url:
            return _chat_completion({"not": "a lesson"})
        return _chat_completion(GROUNDED_LESSON)

    fake_http.responder = responder
    result = _generate()

    assert result["_generated_by"] == "mistral", "a malformed first provider must not win"
    assert [("groq" in r.full_url) for r in fake_http.requests] == [True, False]


def test_json_survives_markdown_fences_and_a_preamble(fake_http, provider_env):
    # models wrap JSON in ```json fences and add chat even when told not to
    provider_env(LLM_PROVIDER_ORDER="groq", GROQ_API_KEY="g")
    fake_http.responder = lambda req: _chat_completion(GROUNDED_LESSON, fenced=True)

    assert _generate()["blocks"][0]["title"] == "Last in, first out"


def test_all_providers_failing_returns_none_so_the_template_takes_over(fake_http, provider_env):
    provider_env(LLM_PROVIDER_ORDER="groq,mistral", GROQ_API_KEY="g", MISTRAL_API_KEY="m")
    fake_http.responder = lambda req: {"choices": []}   # valid HTTP, useless body

    assert _generate() is None, "exhausting every provider must return None, not raise"


# ------------- why a provider failed must be reported, not swallowed -------------

def _http_error(code, message):
    """Raise a real HTTPError with a provider-style JSON error body."""
    import io as _io

    def raiser(req):
        raise urllib.error.HTTPError(
            req.full_url, code, "error", {},
            _io.BytesIO(json.dumps({"error": {"message": message}}).encode()),
        )

    return raiser


def test_a_rejected_api_key_is_reported_not_silently_swallowed(fake_http, provider_env):
    """The failure mode that matters in practice: a key that looks fine but
    is rejected. This used to be indistinguishable from "no LLM configured"."""
    provider_env(LLM_PROVIDER_ORDER="groq", GROQ_API_KEY="wrong-key")
    fake_http.responder = _http_error(401, "Invalid API Key")

    attempts = []
    assert _generate(attempts=attempts) is None

    assert len(attempts) == 1
    assert attempts[0]["provider"] == "groq"
    assert "401" in attempts[0]["outcome"]
    assert "Invalid API Key" in attempts[0]["outcome"]


def test_a_retired_model_name_is_reported_with_the_provider_s_own_message(fake_http, provider_env):
    provider_env(LLM_PROVIDER_ORDER="groq", GROQ_API_KEY="k", GROQ_MODEL="llama-2-70b-chat")
    fake_http.responder = _http_error(400, "The model `llama-2-70b-chat` has been decommissioned")

    attempts = []
    _generate(attempts=attempts)

    assert "decommissioned" in attempts[0]["outcome"], attempts


def test_a_missing_key_is_distinguished_from_a_failing_one(fake_http, provider_env):
    provider_env(LLM_PROVIDER_ORDER="groq,mistral", GROQ_API_KEY="", MISTRAL_API_KEY="")

    attempts = []
    assert _generate(attempts=attempts) is None
    assert [a["provider"] for a in attempts] == ["groq", "mistral"]
    assert all("no API key set" in a["outcome"] for a in attempts), attempts


def test_an_unreachable_provider_is_reported(fake_http, provider_env):
    provider_env(LLM_PROVIDER_ORDER="ollama", OLLAMA_BASE_URL="http://localhost:11434")

    def unreachable(req):
        raise urllib.error.URLError("[WinError 10061] connection refused")

    fake_http.responder = unreachable

    attempts = []
    _generate(attempts=attempts)
    assert "could not reach the provider" in attempts[0]["outcome"], attempts


def test_a_successful_provider_after_a_failing_one_records_both(fake_http, provider_env):
    provider_env(LLM_PROVIDER_ORDER="groq,mistral", GROQ_API_KEY="bad", MISTRAL_API_KEY="good")

    def responder(req):
        if "groq" in req.full_url:
            return _http_error(429, "Rate limit reached")(req)
        return _chat_completion(GROUNDED_LESSON)

    fake_http.responder = responder

    attempts = []
    assert _generate(attempts=attempts)["_generated_by"] == "mistral"
    assert attempts[0]["provider"] == "groq" and "429" in attempts[0]["outcome"]
    assert attempts[1] == {"provider": "mistral", "outcome": "ok"}


def test_provider_attempts_reach_the_explainability_report(uploaded_course, fake_http):
    """End to end: a failing provider has to be visible in the report the UI
    renders, not just inside llm_client."""
    x = _regenerate_with(
        GROUNDED_LESSON, uploaded_course["topic_id"], fake_http,
        responder=_http_error(401, "Invalid API Key"),
    )

    assert x["generated_by"] == "template", "a rejected key must fall back to the template"
    assert x["provider_attempts"], "the report must say WHY the template was used"
    assert any("401" in a["outcome"] for a in x["provider_attempts"]), x["provider_attempts"]


# ------------- 2. the trust score vs the actual uploaded file -------------

def _upload(db_session, uploads_dir, text):
    """Runs the real upload pipeline on `text`, returns (syllabus_id, filename)."""
    import os
    import uuid as uuid_mod

    from app.api.routers.syllabus import process_syllabus

    filename = "my-course-notes.txt"
    dest = os.path.join(uploads_dir, f"{uuid_mod.uuid4()}.txt")
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(text)

    syllabus = models.Syllabus(
        original_filename=filename, stored_path=dest, file_type="text", status="uploaded",
    )
    db_session.add(syllabus)
    db_session.commit()
    db_session.refresh(syllabus)
    sid = str(syllabus.id)
    process_syllabus(sid)
    return sid, filename


def _regenerate_with(lesson, topic_id, fake_http, responder=None):
    """Force a fresh generation of `topic_id`.

    By default the fake Groq returns `lesson`; pass `responder` to drive the
    HTTP layer directly (e.g. to make it raise a 401).
    """
    from app.api.routers.syllabus import _ensure_topic_generated

    fake_http.responder = responder or (lambda req: _chat_completion(lesson))
    db = SessionLocal()
    try:
        topic = db.query(models.Topic).filter(models.Topic.topic_id == topic_id).first()
        _ensure_topic_generated(topic, db, force=True)
        db.refresh(topic)
        return dict(topic.explainability)
    finally:
        db.close()


@pytest.fixture()
def uploaded_course(db_session, uploads_dir, fake_http, provider_env):
    """A real upload, with Groq configured and faked at the HTTP layer."""
    provider_env(LLM_PROVIDER_ORDER="groq", GROQ_API_KEY="test-key", PREGENERATE_UNIT_ENTRY_TOPICS="false")
    fake_http.responder = lambda req: _chat_completion(GROUNDED_LESSON)
    sid, filename = _upload(db_session, uploads_dir, SYLLABUS)
    return {"syllabus_id": sid, "filename": filename, "topic_id": "CS101-U1-T1"}


def test_evidence_is_retrieved_from_the_uploaded_file_itself(uploaded_course, fake_http):
    x = _regenerate_with(GROUNDED_LESSON, uploaded_course["topic_id"], fake_http)

    assert x["generated_by"] == "groq"
    assert x["retrieval_used"] is True, "the lesson must be grounded in the indexed upload"

    # every piece of evidence has to come from the file that was uploaded
    sources = {c["source"] for c in x["retrieved_chunks"]}
    assert sources == {uploaded_course["filename"]}, f"evidence came from {sources}"
    assert any(uploaded_course["filename"] == a["source"] for a in x["attribution"])

    # and the retrieved text has to be the uploaded file's actual words
    joined = " ".join(c["snippet"] for c in x["retrieved_chunks"]).lower()
    assert "last in first out" in joined or "first in first out" in joined


def test_a_grounded_lesson_scores_well_and_every_sentence_is_traced(uploaded_course, fake_http):
    x = _regenerate_with(GROUNDED_LESSON, uploaded_course["topic_id"], fake_http)

    assert x["validation_available"] is True
    assert x["trust_score"] is not None and 0.0 <= x["trust_score"] <= 1.0
    assert x["trust_band"] in ("high", "medium")
    assert x["faithfulness"] >= 0.5
    assert x["hallucination_risk"] <= 0.5
    assert x["similarity_method"] in ("embedding", "lexical")

    # evidence tracing: each generated sentence -> the chunk that supports it
    assert x["evidence_trace"], "a grounded lesson must have a sentence-level trace"
    assert all(t["source"] == uploaded_course["filename"] for t in x["evidence_trace"])
    assert any(t["verdict"] == "supported" for t in x["evidence_trace"])

    # SHAP over the retrieved evidence
    assert x["shap"]["available"] is True
    assert x["shap"]["values"]


def test_a_lesson_about_something_else_is_caught_as_ungrounded(uploaded_course, fake_http):
    x = _regenerate_with(HALLUCINATED_LESSON, uploaded_course["topic_id"], fake_http)

    assert x["generated_by"] == "groq"
    assert x["trust_band"] == "low", f"off-topic content scored {x['trust_band']}"
    assert x["faithfulness"] == 0.0
    assert x["hallucination_risk"] > 0.5
    assert x["flagged_sentences"], "unsupported sentences must be surfaced for review"
    assert all(v["verdict"] != "supported" for v in x["evidence_trace"])

    # the invented figure must be called out specifically
    reasons = " ".join(r for v in x["evidence_trace"] for r in v["reasons"])
    assert "4096" in reasons, f"a number absent from the evidence should be flagged: {reasons}"

    # low trust triggers exactly one strict-mode retry (Phase 3 optimization)
    assert x["optimization"]["regenerated"] is True
    assert x["optimization"]["kept"] in ("first-draft", "strict-regeneration")


def test_grounded_beats_hallucinated_on_every_metric(uploaded_course, fake_http):
    """The comparison that matters: same upload, same topic, same provider -
    only the generated content differs, and every metric must move."""
    good = _regenerate_with(GROUNDED_LESSON, uploaded_course["topic_id"], fake_http)
    bad = _regenerate_with(HALLUCINATED_LESSON, uploaded_course["topic_id"], fake_http)

    assert good["groundedness"] > bad["groundedness"]
    assert good["faithfulness"] > bad["faithfulness"]
    assert good["hallucination_risk"] < bad["hallucination_risk"]
    assert good["semantic_similarity"] > bad["semantic_similarity"]
    assert good["trust_score"] > bad["trust_score"]
    assert good["verdict_counts"]["supported"] > bad["verdict_counts"]["supported"]


def test_a_file_with_no_prose_gets_no_trust_score_rather_than_a_fake_one(
    db_session, uploads_dir, fake_http, provider_env
):
    """A syllabus that is only topic names has nothing to ground against.
    The honest answer is "no score, and here's why" - not a number."""
    provider_env(LLM_PROVIDER_ORDER="", PREGENERATE_UNIT_ENTRY_TOPICS="false")  # no provider -> template
    _upload(db_session, uploads_dir, "Computer Science 101\n\nUnit 1: Basics\n- Variables\n- Functions\n")

    from app.api.routers.syllabus import get_topic_explainability

    db = SessionLocal()
    try:
        x = get_topic_explainability("CS101-U1-T1", db=db)
    finally:
        db.close()

    assert x["generated_by"] == "template"
    assert x["trust_score"] is None, "a made-up number here would be dishonest"
    assert x["validation_note"], "it has to say WHY there is no score"
