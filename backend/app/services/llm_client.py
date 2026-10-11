# tries a few LLM providers in order until one works. LLM_PROVIDER_ORDER
# in .env controls which and in what order.
#
#   ollama  - runs on your own pc, free, needs ollama installed + running
#   mistral - cloud, has free tier, get key at console.mistral.ai
#   groq    - cloud, free tier, super fast, get key at console.groq.com
#   gemini  - cloud, free tier, get key at aistudio.google.com/apikey
#
# if nobody's configured (or they all fail) generate_topic_lesson() just
# returns None and syllabus.py falls back to the plain template generator.
# so the app still works with zero setup, this is just a bonus on top.
#
# only using urllib here, didn't want to add a new pip dep just for this.
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from app.core.config import get_settings

REQUEST_TIMEOUT_SECONDS = 30


def _prompt_for(
    topic_title: str,
    unit_title: str,
    subject_title: str,
    prerequisite_title: Optional[str],
    sequence_order: Optional[int],
    source_excerpt: str,
    evidence_chunks: Optional[List[str]] = None,
    strict: bool = False,
) -> str:
    prereq_line = (
        f'This topic\'s prerequisite (per the syllabus\'s knowledge graph) is "{prerequisite_title}" — '
        f"you can briefly reference it, but don't re-teach it."
        if prerequisite_title
        else "This topic has no prerequisite — it's an entry point into the subject."
    )
    seq_line = f"It is step {sequence_order} in the subject's learning path." if sequence_order else ""

    if evidence_chunks:
        numbered = "\n\n".join(f"[{i}] {c[:1200]}" for i, c in enumerate(evidence_chunks, start=1))
        evidence_section = (
            "Retrieved evidence from the learner's own material (numbered). Ground the lesson in it: "
            "explain what it says, in your own words, and prefer it over outside knowledge.\n"
            f"{numbered}"
        )
        if strict:
            evidence_section += (
                "\n\nSTRICT MODE: a previous draft drifted from this evidence. State only facts that the "
                "evidence above supports. Do not add numbers, names or claims that are not in it. If the "
                "evidence is thin, write fewer, shorter subtopics rather than inventing detail."
            )
    else:
        evidence_section = (
            "Original syllabus excerpt for grounding (may be sparse - use your own subject knowledge to "
            f"fill gaps, but stay on-topic):\n\"\"\"{source_excerpt[:1500]}\"\"\""
        )

    return f"""You are writing a full lesson for a self-study app. Subject: "{subject_title}". Unit: "{unit_title}". Topic: "{topic_title}". {prereq_line} {seq_line}

{evidence_section}

Break "{topic_title}" down into its natural conceptual subtopics (however many genuinely exist for this specific topic - could be 2, could be 6, don't pad or split artificially) and explain EACH ONE fully and separately, the way a real teacher would when covering this topic in depth: what it is, why it matters, and how it fits into "{topic_title}" as a whole. Every subtopic needs its own real explanation, not a one-line summary.

Respond with ONLY a single JSON object (no markdown fences, no commentary) with EXACTLY this shape:
{{
  "blocks": [
    {{"title": "name of this specific subtopic", "body": "a full, clear, accurate explanation of this subtopic - several sentences, real teaching content, not filler", "source": "string, e.g. 'Generated explanation'"}}
  ],
  "quiz": [
    {{"q": "string question", "options": ["opt1", "opt2", "opt3"], "answer": 0}}
  ],
  "arrange": [
    {{"term": "string", "keywords": ["word1","word2","word3"], "distractors": ["wrong1","wrong2"], "definition": "one sentence definition"}}
  ],
  "fill": [
    {{"text": "sentence with one or more ___ blanks", "answers": ["answer1"], "bank": ["answer1","decoy1","decoy2"]}}
  ],
  "catch": [
    {{"term": "string related to the topic", "ok": true}},
    {{"term": "string unrelated to the topic", "ok": false}}
  ],
  "notes": ["one short study tip string"]
}}
"blocks" must cover every real subtopic of "{topic_title}" fully - do not compress this to one block. 1 quiz question, 1 arrange item, 1 fill item, 2 catch items, 1 note. "answer" in quiz is a 0-based index into "options". Keep everything factually correct and specific to "{topic_title}", not generic filler."""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    # models like to wrap json in ```json fences or add "sure, here's the lesson:" before it
    # even when told not to, so just grab whatever's between the first { and last }
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def _validate_shape(data: Dict[str, Any]) -> bool:
    required_keys = {"blocks", "quiz", "arrange", "fill", "catch", "notes"}
    if not isinstance(data, dict) or not required_keys.issubset(data.keys()):
        return False
    if not data["blocks"] or not isinstance(data["blocks"], list):
        return False
    if not all("title" in b and "body" in b for b in data["blocks"]):
        return False
    return True


def _post_json(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    errors: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """POST JSON, returning the decoded body or None.

    `errors` collects a short, human-readable reason for any failure. Without
    it, a wrong API key, a retired model name and "no provider configured"
    were all indistinguishable: every one of them just returned None and the
    lesson quietly came out of the template, with the UI saying "no LLM
    configured" even though one was. The reason is surfaced in the
    explainability report so a misconfiguration is visible instead of
    looking like the feature doesn't work.
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={**headers, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                if errors is not None:
                    errors.append(f"HTTP {resp.status}")
                return None
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # The body of a 4xx is where providers put the actual reason
        # ("invalid_api_key", "model_decommissioned", "rate_limit_exceeded").
        detail = ""
        try:
            raw = json.loads(exc.read().decode("utf-8", "replace"))
            detail = str(raw.get("error", {}).get("message") or raw.get("message") or "")[:200]
        except Exception:
            pass
        if errors is not None:
            errors.append(f"HTTP {exc.code}{': ' + detail if detail else ''}")
        return None
    except (urllib.error.URLError, TimeoutError) as exc:
        if errors is not None:
            errors.append(f"could not reach the provider ({getattr(exc, 'reason', exc)})")
        return None
    except (json.JSONDecodeError, ValueError) as exc:
        if errors is not None:
            errors.append(f"response was not valid JSON ({exc})")
        return None


def _call_ollama(prompt: str, errors: Optional[List[str]] = None) -> Optional[str]:
    # local ollama server, no key needed
    settings = get_settings()
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    result = _post_json(
        url,
        headers={},
        payload={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False},
        errors=errors,
    )
    if not result:
        return None
    text = result.get("response")
    if not text and errors is not None:
        errors.append("response had no 'response' field")
    return text


def _call_mistral(prompt: str, errors: Optional[List[str]] = None) -> Optional[str]:
    settings = get_settings()
    if not settings.MISTRAL_API_KEY:
        if errors is not None:
            errors.append("no API key set (MISTRAL_API_KEY)")
        return None
    result = _post_json(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.MISTRAL_API_KEY}"},
        payload={
            "model": settings.MISTRAL_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
        },
        errors=errors,
    )
    if not result:
        return None
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        if errors is not None:
            errors.append("unexpected response shape (no choices[0].message.content)")
        return None


def _call_groq(prompt: str, errors: Optional[List[str]] = None) -> Optional[str]:
    settings = get_settings()
    if not settings.GROQ_API_KEY:
        if errors is not None:
            errors.append("no API key set (GROQ_API_KEY)")
        return None
    result = _post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        payload={
            "model": settings.GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
        },
        errors=errors,
    )
    if not result:
        return None
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        if errors is not None:
            errors.append("unexpected response shape (no choices[0].message.content)")
        return None


def _call_gemini(prompt: str, errors: Optional[List[str]] = None) -> Optional[str]:
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        if errors is not None:
            errors.append("no API key set (GEMINI_API_KEY)")
        return None
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
    )
    result = _post_json(
        url,
        headers={},
        payload={"contents": [{"parts": [{"text": prompt}]}]},
        errors=errors,
    )
    if not result:
        return None
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        if errors is not None:
            errors.append("unexpected response shape (no candidates[0].content.parts[0].text)")
        return None


_PROVIDERS = {
    "ollama": _call_ollama,
    "mistral": _call_mistral,
    "groq": _call_groq,
    "gemini": _call_gemini,
}


def generate_topic_lesson(
    topic_title: str,
    unit_title: str,
    subject_title: str,
    prerequisite_title: Optional[str],
    sequence_order: Optional[int],
    source_excerpt: str = "",
    subject_id: Optional[str] = None,
    context_chunks: Optional[List[Dict[str, Any]]] = None,
    strict: bool = False,
    attempts: Optional[List[Dict[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    # Phase 3 - LLM response generation: prompt construction + provider call.
    # Retrieval (Phase 2) happens BEFORE this, in services/rag_pipeline.py, and
    # is passed in as context_chunks; with none, the raw excerpt is used.
    # goes through the provider list one by one, returns first valid result.
    # None means everybody failed / nobody's configured, caller should use the template instead.
    settings = get_settings()

    evidence_texts = [c["text"] for c in (context_chunks or [])]
    prompt = _prompt_for(
        topic_title, unit_title, subject_title, prerequisite_title, sequence_order,
        source_excerpt, evidence_chunks=evidence_texts or None, strict=strict,
    )

    # `attempts` records what each provider did, so the UI can tell
    # "no provider configured" apart from "configured, but the key was
    # rejected" or "that model name is retired" - which used to look
    # identical from the outside (a template lesson, no explanation).
    def note(provider: str, outcome: str) -> None:
        if attempts is not None:
            attempts.append({"provider": provider, "outcome": outcome})

    for provider_name in settings.llm_provider_order_list:
        call = _PROVIDERS.get(provider_name)
        if not call:
            note(provider_name, "unknown provider name in LLM_PROVIDER_ORDER")
            continue
        errors: List[str] = []
        raw_text = call(prompt, errors=errors)
        if not raw_text:
            note(provider_name, errors[0] if errors else "no response")
            continue
        data = _extract_json(raw_text)
        if not data:
            note(provider_name, "replied, but the reply contained no JSON object")
            continue
        if not _validate_shape(data):
            note(provider_name, "replied with JSON that is missing required lesson fields")
            continue
        note(provider_name, "ok")
        data["_generated_by"] = provider_name
        return data

    return None
