"""
summarizer.py
Summaries and key points.

Strategy (changed for speed):
  * Normal documents (fits in the model context) -> ONE call, no map-reduce.
  * Very long documents -> parallel MAP over large chunks, then one REDUCE.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from typing import List

from .gemini_client import GeminiClient

# ~300k characters is roughly 75k tokens: comfortably inside Flash-class context.
SINGLE_PASS_CHARS = 300_000
LONG_CHUNK_CHARS = 60_000

LENGTH_HINT = {
    "brief": "in about 150-200 words",
    "detailed": "in about 350-500 words",
    "comprehensive": "in about 600-900 words",
}

FORMAT_RULES = """FORMAT - follow exactly:
- Plain flowing prose in short paragraphs (3-5 sentences each).
- Separate paragraphs with exactly ONE blank line.
- No markdown headers, bullet points, numbered lists, bold or italics.
- Weave figures and formulas into sentences instead of listing them.
- Use only information present in the source. Do not add outside facts.
- Output the summary text only: no title, labels or preamble."""


def clean_text(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk_text(text: str, max_chars: int = LONG_CHUNK_CHARS, overlap: int = 300) -> List[str]:
    text = clean_text(text)
    chunks, start = [], 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return [c for c in chunks if c.strip()]


def summarize_document(client: GeminiClient, text: str, style: str = "detailed") -> str:
    """Single-call summary of a document that fits in context."""
    hint = LENGTH_HINT.get(style, LENGTH_HINT["detailed"])
    prompt = f"""You are an expert study assistant. Write a study summary of the
document below {hint}, as if explaining the topic directly to a student.
Cover the main ideas in a logical order and keep important definitions,
formulas, names and numbers accurate.

{FORMAT_RULES}

DOCUMENT:
\"\"\"
{clean_text(text)}
\"\"\"
"""
    return client.generate(prompt, temperature=0.3)


def map_summarize_chunk(client: GeminiClient, chunk: str, idx: int, total: int) -> str:
    prompt = f"""Summarize part {idx + 1} of {total} of a study document.
Preserve every important fact, definition, formula, name and concept.
Be concise but complete. Plain text only. Use only the excerpt.

EXCERPT:
\"\"\"
{chunk}
\"\"\"
"""
    return client.generate(prompt, temperature=0.3)


def reduce_summaries(client: GeminiClient, chunk_summaries: List[str], style: str = "detailed") -> str:
    hint = LENGTH_HINT.get(style, LENGTH_HINT["detailed"])
    combined = "\n\n".join(f"[Part {i + 1}]\n{s}" for i, s in enumerate(chunk_summaries))
    prompt = f"""Combine these partial summaries of ONE document into a single
study summary {hint}. Remove redundancy and keep a logical flow. Do not mention
"parts" or the summarization process.

{FORMAT_RULES}

PARTIAL SUMMARIES:
\"\"\"
{combined}
\"\"\"
"""
    return client.generate(prompt, temperature=0.3)


def summarize_long(client: GeminiClient, text: str, style: str = "detailed") -> str:
    """Parallel map-reduce, used only for very long documents."""
    chunks = chunk_text(text)
    with ThreadPoolExecutor(max_workers=min(6, len(chunks))) as ex:
        parts = list(ex.map(
            lambda a: map_summarize_chunk(client, a[1], a[0], len(chunks)),
            enumerate(chunks),
        ))
    return reduce_summaries(client, parts, style)


def generate_key_points(client: GeminiClient, source: str, num_points: int = 10) -> List[str]:
    prompt = f"""From the study material below, extract the {num_points} most
important points a student must remember before an exam. Each point is one
self-contained sentence. Use only the material; do not add outside facts.
Return a JSON array of strings.

MATERIAL:
\"\"\"
{source}
\"\"\"
"""
    data = client.generate_json(prompt, list[str], temperature=0.3)
    return [str(p).strip() for p in data if str(p).strip()]