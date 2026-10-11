"""
Parse raw syllabus text → FIXED OUTPUT SCHEMA exactly.
"""
import re
from typing import List, Dict, Any
import spacy

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    nlp = spacy.blank("en")
    if "sentencizer" not in nlp.pipe_names:
        nlp.add_pipe("sentencizer")

# ---------------------------------------------------------------------------
# subject_id derivation logic (documented)
# ---------------------------------------------------------------------------
def derive_subject_id(subject_title: str) -> str:
    """
    Deterministic derivation when syllabus does not give an explicit code.
    Rules (in order):
    1. If the title already contains a code-like token (e.g. CS101, MATH-201) → use it uppercased.
    2. Otherwise take the first letter of every significant word (length > 2),
       uppercase, and append "101" as a default level suffix.
    Examples:
        "Computer Science"          → CS101
        "Introduction to Algorithms"→ ITA101
        "Data Structures & Algorithms" → DSA101
        "CS 301 - Operating Systems"→ CS301
    """
    # Look for existing code
    code_match = re.search(r"\b([A-Z]{2,5}[-\s]?\d{2,4})\b", subject_title, re.I)
    if code_match:
        return re.sub(r"[-\s]", "", code_match.group(1)).upper()

    words = re.findall(r"[A-Za-z]+", subject_title)
    significant = [w for w in words if len(w) > 2 and w.lower() not in {
        "the", "and", "for", "introduction", "to", "of", "in", "with", "using"
    }]
    if not significant:
        significant = words[:3] if words else ["SUBJ"]

    acronym = "".join(w[0].upper() for w in significant[:4])
    return f"{acronym}101"

# ---------------------------------------------------------------------------
# duration_minutes estimation heuristic (documented – tune later)
# ---------------------------------------------------------------------------
def estimate_duration_minutes(topic_title: str) -> int:
    """
    Simple heuristic used when syllabus does not state duration.
    - Base = 45 minutes
    - +15 if title contains "advanced", "deep", "project", "lab", "case study"
    - -15 if title contains "overview", "intro", "introduction", "basics"
    Clamp to [20, 120]
    """
    t = topic_title.lower()
    duration = 45
    if any(k in t for k in ("advanced", "deep", "project", "lab", "case study", "implementation")):
        duration += 15
    if any(k in t for k in ("overview", "intro", "introduction", "basics", "fundamentals")):
        duration -= 15
    return max(20, min(120, duration))

# ---------------------------------------------------------------------------
# Core parser
# ---------------------------------------------------------------------------
def parse_syllabus_text(raw_text: str) -> Dict[str, Any]:
    """
    Returns the exact fixed schema:
    {
      "curriculum": {
        "version": "1.0",
        "subjects": [ ... ]
      }
    }

    Handles two document shapes:
    1. Multi-subject syllabus — an uploaded file that covers more than one
       subject, each introduced with an explicit heading such as
       "Subject: Computer Science", "Course 2: Physics", "SUBJECT - Maths".
       Each subject is parsed independently into its own units/topics.
    2. Single-subject syllabus (the common case, and everything this parser
       supported before) — no repeated subject-level markers, so the whole
       document is one subject and its first prominent heading is used as
       the title, exactly as before.
    """
    if not raw_text or not raw_text.strip():
        # Fallback empty but valid schema
        return {
            "curriculum": {
                "version": "1.0",
                "subjects": []
            }
        }

    # Normalize whitespace
    text = re.sub(r"[ \t]+", " ", raw_text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    subject_chunks = _split_into_subjects(text)

    used_ids: set = set()
    if subject_chunks:
        subjects = [
            _build_subject(title, body, used_ids)
            for title, body in subject_chunks
        ]
    else:
        subject_title = _extract_subject_title(text)
        subjects = [_build_subject(subject_title, text, used_ids)]

    return {
        "curriculum": {
            "version": "1.0",
            "subjects": subjects
        }
    }


def _build_subject(subject_title: str, body: str, used_ids: set) -> Dict[str, Any]:
    """Parse one subject's worth of text into the fixed subject schema.

    `used_ids` is shared across all subjects in a single parse call so that
    if two subjects derive the same id (e.g. two subjects that both start
    with "Introduction to ...") the second one gets a numeric suffix instead
    of silently colliding/overwriting the first.
    """
    subject_title = (subject_title or "Untitled Subject").strip() or "Untitled Subject"
    subject_id = derive_subject_id(subject_title)
    base_id = subject_id
    suffix = 2
    while subject_id in used_ids:
        subject_id = f"{base_id}-{suffix}"
        suffix += 1
    used_ids.add(subject_id)

    # Only feed the text *before* the first unit heading to the description
    # extractor — otherwise unit/topic lines bleed into the description
    # (e.g. "Introduction to ... Unit 1: Fundamentals\n- Variables...").
    first_unit_match = _UNIT_PATTERN.search(body)
    intro_text = body[: first_unit_match.start()] if first_unit_match else body
    description = _extract_description(intro_text, subject_title)

    units_raw = _split_into_units(body)
    units = []
    for unit_num, unit_title, unit_body in units_raw:
        topics = _extract_topics(unit_body, subject_id, unit_num)
        units.append({
            "unit_number": unit_num,
            "unit_title": unit_title.strip(),
            "topics": topics
        })

    # If no units detected, treat the whole subject body as Unit 1
    if not units:
        topics = _extract_topics(body, subject_id, 1)
        units = [{
            "unit_number": 1,
            "unit_title": "Main Content",
            "topics": topics
        }]

    return {
        "subject_id": subject_id,
        "subject_title": subject_title,
        "description": description,
        "units": units
    }


def _split_into_subjects(text: str) -> List[tuple]:
    """
    Returns a list of (subject_title, subject_body) chunks when the document
    contains 2+ explicit subject-level headings, e.g.:
        Subject: Computer Science
        Course 2: Physics
        SUBJECT - Mathematics

    Only splits when at least two such markers are found. A single marker
    (or none) means the document covers just one subject, and this returns
    an empty list so the caller falls back to the existing single-subject
    heading-guessing logic — this keeps every previously-supported syllabus
    format parsing exactly as it did before.

    Deliberately narrower than the unit-heading pattern (Unit/Chapter/
    Module/Part): those words legitimately appear inside a single-subject
    syllabus, but "Subject:"/"Course N:" style headings are a much stronger,
    less ambiguous signal that a *new subject* is starting.
    """
    subject_pattern = re.compile(
        r"(?:^|\n)\s*(?:Subject|SUBJECT|Course|COURSE)\s*"
        r"(\d{1,2})?\s*[\.\-:]\s*([^\n]{2,100})",
        re.IGNORECASE
    )
    matches = list(subject_pattern.finditer(text))
    if len(matches) < 2:
        return []

    chunks = []
    for i, m in enumerate(matches):
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        chunks.append((title, body))
    return chunks

def _extract_subject_title(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Prefer lines that look like titles (short, title-case or uppercase)
    for line in lines[:15]:
        if 5 < len(line) < 80 and not line.lower().startswith(("unit", "chapter", "module", "week")):
            # Remove common prefixes
            cleaned = re.sub(r"^(subject|course|title)\s*[:\-]\s*", "", line, flags=re.I)
            return cleaned.strip()
    return "Untitled Subject"

def _extract_description(text: str, subject_title: str) -> str:
    # Take first 1-2 sentences after the title
    doc = nlp(text[:1500])
    sents = list(doc.sents)
    desc_parts = []
    for s in sents[:3]:
        if subject_title.lower() not in s.text.lower() and len(s.text) > 30:
            desc_parts.append(s.text.strip())
        if len(desc_parts) >= 2:
            break
    return " ".join(desc_parts)[:400] if desc_parts else f"Syllabus for {subject_title}"

_UNIT_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:Unit|UNIT|Chapter|CHAPTER|Module|MODULE|Part|PART)\s*[-:]?\s*"
    r"([IVXLC\d]+)[\s\.\-:]*([^\n]{0,80})",
    re.IGNORECASE
)


def _split_into_units(text: str) -> List[tuple]:
    """
    Returns list of (unit_number, unit_title, unit_body)
    Looks for patterns: Unit 1, UNIT-I, Chapter 2, Module 3, etc.
    """
    matches = list(_UNIT_PATTERN.finditer(text))
    if not matches:
        return []

    units = []
    for i, m in enumerate(matches):
        num_str = m.group(1).strip()
        title = m.group(2).strip() or f"Unit {num_str}"
        # Convert roman / arabic
        unit_num = _roman_or_int(num_str)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        units.append((unit_num, title, body))
    return units

def _roman_or_int(s: str) -> int:
    s = s.upper().strip()
    roman = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
    if s in roman:
        return roman[s]
    try:
        return int(s)
    except ValueError:
        return 1

def _extract_topics(unit_body: str, subject_id: str, unit_number: int) -> List[Dict[str, Any]]:
    """
    Extract topics from a unit body.
    Strategies (in order of preference):
    1. Numbered / bulleted lists
    2. Lines that look like topic headings (short, no period at end)
    3. spaCy noun chunks as last resort
    """
    topics = []
    seen = set()

    # 1. Numbered / lettered / bullet lists
    # Min length is intentionally low (3, not the 8+ used for the heading
    # fallback below): an explicit bullet/number already signals "this is a
    # list item", so short-but-valid topics like "Arrays" or "SQL" shouldn't
    # be silently dropped just for being short.
    list_pat = re.compile(
        r"(?:^|\n)\s*(?:[\(\[]?[a-zA-Z0-9]{1,3}[\)\].\-]|\•|\-|\*)\s+([^\n]{3,120})",
        re.MULTILINE
    )
    for m in list_pat.finditer(unit_body):
        title = m.group(1).strip().rstrip(".")
        title = re.sub(r"\s+", " ", title)
        if title.lower() not in seen and len(title) > 5:
            seen.add(title.lower())
            topics.append(title)

    # 2. Fallback – short lines that look like headings
    if len(topics) < 2:
        for line in unit_body.splitlines():
            line = line.strip()
            if 10 < len(line) < 90 and not line.endswith((".", ":", ";")):
                if line.lower() not in seen:
                    seen.add(line.lower())
                    topics.append(line)

    # 3. Last resort – spaCy noun chunks (take top meaningful ones)
    if len(topics) < 2:
        try:
            doc = nlp(unit_body[:3000])
            for chunk in doc.noun_chunks:
                t = chunk.text.strip()
                if 8 < len(t) < 80 and t.lower() not in seen:
                    seen.add(t.lower())
                    topics.append(t)
                    if len(topics) >= 8:
                        break
        except Exception:
            pass

    # Build final topic objects with correct topic_id
    result = []
    for idx, title in enumerate(topics[:15], start=1):  # cap at 15 topics per unit
        topic_id = f"{subject_id}-U{unit_number}-T{idx}"
        result.append({
            "topic_id": topic_id,
            "title": title,
            "duration_minutes": estimate_duration_minutes(title)
        })
    return result