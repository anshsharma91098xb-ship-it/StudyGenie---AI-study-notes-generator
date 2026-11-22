"""
quiz_flashcards.py
MCQ quiz and flashcard generation using Gemini's native JSON mode.
"""

import random
from typing import Any, Dict, List

from pydantic import BaseModel

from .gemini_client import GeminiClient


class QuizItem(BaseModel):
    question: str
    options: List[str]
    answer_index: int
    explanation: str


class CardItem(BaseModel):
    front: str
    back: str


def _shuffle_options(item: Dict[str, Any]) -> Dict[str, Any]:
    """LLMs over-place the correct answer in the first slot; randomise it."""
    opts, ans = item["options"], item["answer_index"]
    correct = opts[ans]
    random.shuffle(opts)
    item["answer_index"] = opts.index(correct)
    return item


def generate_mcq_quiz(client: GeminiClient, source: str, num_questions: int = 8) -> List[Dict[str, Any]]:
    prompt = f"""Create {num_questions} multiple-choice questions that test
understanding of the study material below.

Rules:
- Exactly 4 options per question and exactly one correct answer.
- Wrong options must be plausible (common misconceptions or related terms).
- Base every question and answer only on the material. No outside facts.
- Mix recall questions and questions that need understanding or application.
- answer_index is the 0-based index of the correct option.
- explanation: 1-2 sentences saying why the answer is correct.

MATERIAL:
\"\"\"
{source}
\"\"\"
"""
    try:
        data = client.generate_json(prompt, list[QuizItem], temperature=0.5)
    except Exception:
        return []
    cleaned = []
    for item in data:
        try:
            opts = [str(o) for o in item["options"]]
            idx = int(item["answer_index"])
            if len(opts) >= 2 and 0 <= idx < len(opts) and item.get("question"):
                cleaned.append(_shuffle_options({
                    "question": item["question"], "options": opts,
                    "answer_index": idx, "explanation": item.get("explanation", ""),
                }))
        except (KeyError, TypeError, ValueError):
            continue
    return cleaned


def generate_flashcards(client: GeminiClient, source: str, num_cards: int = 10) -> List[Dict[str, str]]:
    prompt = f"""Create {num_cards} flashcards from the study material below.
Each has a short "front" (a term or question, under 12 words) and a concise
"back" (the answer, 1-3 sentences). Cover different concepts; no duplicates.
Use only the material.

MATERIAL:
\"\"\"
{source}
\"\"\"
"""
    try:
        data = client.generate_json(prompt, list[CardItem], temperature=0.4)
    except Exception:
        return []
    return [d for d in data if isinstance(d, dict) and d.get("front") and d.get("back")]# ui_components.py
"""
Quiz and flashcards built from native Streamlit widgets.
No iframes, no custom JS: they follow the app theme and stay fast.
"""

import html
import random

import streamlit as st

STATE_KEYS = ("qz_idx", "qz_score", "qz_choice", "fc_idx", "fc_flipped", "fc_cards")


def reset_ui_state():
    for k in STATE_KEYS:
        st.session_state.pop(k, None)


def render_quiz(questions: list):
    s = st.session_state
    s.setdefault("qz_idx", 0)
    s.setdefault("qz_score", 0)
    s.setdefault("qz_choice", None)
    n, i = len(questions), s.qz_idx

    if i >= n:
        pct = round(100 * s.qz_score / n)
        st.subheader(f"You scored {s.qz_score} of {n} ({pct}%)")
        if st.button("Retake quiz", key="qz_retake"):
            s.qz_idx, s.qz_score, s.qz_choice = 0, 0, None
            random.shuffle(questions)
            st.rerun()
        return

    q, choice = questions[i], s.qz_choice
    st.progress(i / n, text=f"Question {i + 1} of {n}")
    st.markdown(f"#### {q['question']}")

    for j, opt in enumerate(q["options"]):
        label = f"{chr(65 + j)}.  {opt}"
        if choice is None:
            if st.button(label, key=f"qz_{i}_{j}", use_container_width=True):
                s.qz_choice = j
                if j == q["answer_index"]:
                    s.qz_score += 1
                st.rerun()
        elif j == q["answer_index"]:
            st.success(label)
        elif j == choice:
            st.error(label)
        else:
            st.markdown(f"<div class='dim-option'>{html.escape(label)}</div>", unsafe_allow_html=True)

    if choice is not None:
        if q.get("explanation"):
            st.caption(q["explanation"])
        last = i + 1 >= n
        if st.button("See results" if last else "Next question", key=f"qz_next_{i}", type="primary"):
            s.qz_idx += 1
            s.qz_choice = None
            st.rerun()


def render_flashcards(cards: list):
    s = st.session_state
    if "fc_cards" not in s:
        s.fc_cards = list(cards)
    s.setdefault("fc_idx", 0)
    s.setdefault("fc_flipped", False)
    deck, i = s.fc_cards, s.fc_idx

    st.caption(f"Card {i + 1} of {len(deck)}")
    with st.container(key="flashcard"):
        st.markdown(f"<div class='card-face'>{html.escape(deck[i]['front'])}</div>", unsafe_allow_html=True)
        if s.fc_flipped:
            st.divider()
            st.markdown(f"<div class='card-face card-back'>{html.escape(deck[i]['back'])}</div>",
                        unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Previous", use_container_width=True, key="fc_prev"):
        s.fc_idx, s.fc_flipped = (i - 1) % len(deck), False
        st.rerun()
    if c2.button("Hide answer" if s.fc_flipped else "Show answer",
                 use_container_width=True, key="fc_flip", type="primary"):
        s.fc_flipped = not s.fc_flipped
        st.rerun()
    if c3.button("Next", use_container_width=True, key="fc_next"):
        s.fc_idx, s.fc_flipped = (i + 1) % len(deck), False
        st.rerun()
    if c4.button("Shuffle", use_container_width=True, key="fc_shuffle"):
        random.shuffle(deck)
        s.fc_idx, s.fc_flipped = 0, False
        st.rerun()