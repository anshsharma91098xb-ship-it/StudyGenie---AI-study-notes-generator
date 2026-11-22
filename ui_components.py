# ui_components.py
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
            if st.button(label, key=f"qz_{i}_{j}", width="stretch"):
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
        if q.get("evidence"):
            mark = "verified in your file" if q.get("grounded") else "could not be verified in your file"
            st.caption(f"Source text ({mark}): \"{q['evidence']}\"")
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
    if c1.button("Previous", width="stretch", key="fc_prev"):
        s.fc_idx, s.fc_flipped = (i - 1) % len(deck), False
        st.rerun()
    if c2.button("Hide answer" if s.fc_flipped else "Show answer",
                 width="stretch", key="fc_flip", type="primary"):
        s.fc_flipped = not s.fc_flipped
        st.rerun()
    if c3.button("Next", width="stretch", key="fc_next"):
        s.fc_idx, s.fc_flipped = (i + 1) % len(deck), False
        st.rerun()
    if c4.button("Shuffle", width="stretch", key="fc_shuffle"):
        random.shuffle(deck)
        s.fc_idx, s.fc_flipped = 0, False
        st.rerun()