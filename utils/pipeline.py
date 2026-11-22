"""
pipeline.py
Runs summary, key points, quiz and flashcards IN PARALLEL.

Normal documents: all four tasks start at once, each reading the source text.
Very long documents: summary first (parallel map-reduce), then the other
three in parallel from the summary.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, Optional

from .gemini_client import GeminiClient
from .quiz_flashcards import generate_flashcards, generate_mcq_quiz
from .summarizer import (SINGLE_PASS_CHARS, clean_text, generate_key_points,
                         summarize_document, summarize_long)


def run_pipeline(
    client: GeminiClient,
    text: str,
    style: str,
    n_points: int,
    n_quiz: int,
    n_cards: int,
    on_done: Optional[Callable[[str, float], None]] = None,
) -> Dict:
    """Returns {"results": {...}, "errors": {...}, "seconds": float, "mode": str}."""
    t0 = time.time()
    results: Dict = {}
    errors: Dict = {}
    text = clean_text(text)
    long_doc = len(text) > SINGLE_PASS_CHARS
    source = text

    if long_doc:
        try:
            results["summary"] = summarize_long(client, text, style)
            source = results["summary"]
        except Exception as e:  # noqa: BLE001
            errors["summary"] = str(e)
            return {"results": results, "errors": errors,
                    "seconds": time.time() - t0, "mode": "map-reduce"}
        if on_done:
            on_done("summary", time.time() - t0)

    tasks = {
        "key_points": lambda: generate_key_points(client, source, n_points),
        "quiz": lambda: generate_mcq_quiz(client, source, n_quiz),
        "flashcards": lambda: generate_flashcards(client, source, n_cards),
    }
    if not long_doc:
        tasks["summary"] = lambda: summarize_document(client, text, style)

    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futures = {ex.submit(fn): name for name, fn in tasks.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as e:  # noqa: BLE001
                errors[name] = str(e)
            if on_done:
                on_done(name, time.time() - t0)

    return {"results": results, "errors": errors,
            "seconds": time.time() - t0,
            "mode": "map-reduce" if long_doc else "single-pass"}