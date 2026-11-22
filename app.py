"""
app.py
StudyGenie: turn a PDF into a summary, key points, a quiz and flashcards.
UI: dashboard of four tiles, with a light (white/purple) and dark (black/grey/purple) theme.
"""

import hashlib
import html
from pathlib import Path

import streamlit as st

from ui_components import render_flashcards, render_quiz, reset_ui_state
from utils.gemini_client import GeminiClient, GeminiGenerationError
from utils.pdf_extractor import SUPPORTED_TYPES, estimate_reading_stats, extract_text
from utils.pipeline import run_pipeline

st.set_page_config(page_title="StudyGenie", page_icon="📘", layout="wide", initial_sidebar_state="expanded")

# ---------------------------------------------------------------- theme
THEMES = {
    "light": dict(bg="#FFFFFF", tile="#F6F3FF", border="#E3DCF5", text="#1A1530",
                  muted="#5B5675", accent="#6D28D9", btn="#6D28D9", btnh="#5B21B6"),
    "dark":  dict(bg="#0E0E11", tile="#17171C", border="#2F2F3A", text="#ECECF1",
                  muted="#A6A6B8", accent="#B79CFF", btn="#7C3AED", btnh="#6D28D9"),
}


def inject_theme(dark: bool):
    t = THEMES["dark" if dark else "light"]
    root = ":root{" + "".join(f"--{k}:{v};" for k, v in t.items()) + "}"
    css_file = Path(__file__).parent / "assets" / "style.css"
    css = css_file.read_text(encoding="utf-8") if css_file.exists() else ""
    st.markdown(f"<style>{root}{css}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------- state
for _k, _v in {"data": None, "meta": None, "cache": {}, "api_key": "",
               "view": None, "dark": False}.items():
    st.session_state.setdefault(_k, _v)

inject_theme(st.session_state.dark)

# ---------------------------------------------------------------- theme button (top right, next to Deploy)
def _toggle_theme():
    st.session_state.dark = not st.session_state.dark


_dark = st.session_state.dark
with st.container(key="theme_toggle"):
    st.button(
        "Switch theme", key="theme_btn", on_click=_toggle_theme,
        icon=":material/light_mode:" if _dark else ":material/dark_mode:",
        help="Switch to Light Mode" if _dark else "Switch to Dark Mode",
    )

# ---------------------------------------------------------------- sidebar settings
with st.sidebar:
    st.subheader("Settings")
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        secret_key = ""
    if secret_key:
        own = st.text_input("Use your own Gemini API key (optional)", type="password")
        st.session_state.api_key = own.strip() or secret_key
    else:
        st.session_state.api_key = st.text_input(
            "Gemini API key", type="password", value=st.session_state.api_key,
            help="Free key at aistudio.google.com/app/apikey").strip()
    st.markdown("Summary length")
    style = st.segmented_control(
        "Summary length", ["brief", "detailed", "comprehensive"], default="detailed",
        selection_mode="single", format_func=str.capitalize,
        label_visibility="collapsed", key="summary_len", width="stretch",
    ) or "detailed"  # keeps "detailed" if the user clicks the active box again
    n_points = st.slider("Key points", 5, 20, 10)
    n_quiz = st.slider("Quiz questions", 5, 15, 8)
    n_cards = st.slider("Flashcards", 5, 20, 10)
    st.caption("Settings apply to the next file you upload.")

# ---------------------------------------------------------------- brand
st.markdown("<div class='brand'>StudyGenie</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------- generation
def generate(uploaded, style, n_points, n_quiz, n_cards) -> bool:
    try:
        raw = uploaded.getvalue()
        key = hashlib.sha256(raw + f"{style}{n_points}{n_quiz}{n_cards}".encode()).hexdigest()
        cache = st.session_state.cache

        if key in cache:  # same file and settings: instant
            st.session_state.data, st.session_state.meta = cache[key]
        else:
            with st.status("Reading file...", expanded=True) as status:
                text, count, unit = extract_text(uploaded)
                size = "Word document" if unit == "document" else f"{count} {unit}"
                if not text.strip():
                    status.update(label="No text found", state="error")
                    st.error("No readable text was found. The file may be scanned or made of images. "
                             "Try a text-based file.")
                    return False
                words = estimate_reading_stats(text)["word_count"]
                status.write(f"{words:,} words, {size}. Generating all four outputs together...")
                labels = {"summary": "Summary", "key_points": "Key points",
                          "quiz": "Quiz", "flashcards": "Flashcards"}
                client = GeminiClient(st.session_state.api_key)
                out = run_pipeline(
                    client, text, style, n_points, n_quiz, n_cards,
                    on_done=lambda name, t: status.write(f"{labels[name]} ready ({t:.0f}s)"),
                )
                status.update(label=f"Done in {out['seconds']:.0f}s", state="complete", expanded=False)

            meta = {"file": uploaded.name, "size": size, "seconds": out["seconds"],
                    "model": client.last_used_model, "mode": out["mode"], "errors": out["errors"]}
            st.session_state.data, st.session_state.meta = out["results"], meta
            if not out["errors"]:
                cache[key] = (out["results"], meta)
        st.session_state.view = None
        reset_ui_state()
        return True
    except GeminiGenerationError as e:
        st.error("Gemini could not generate a response. Check your API key and quota.")
        st.code(str(e), language=None)
    except ValueError as e:
        st.error(str(e))
    except Exception as e:  # noqa: BLE001
        st.error(f"Something went wrong: {e}")
    return False


# ---------------------------------------------------------------- landing
def landing():
    st.markdown("<h1 class='hero'>Turn your notes into study materials</h1>", unsafe_allow_html=True)
    st.caption("Upload a PDF, Word or PowerPoint file to get a summary, key points, a quiz and flashcards.")
    uploaded = st.file_uploader("Study file", type=SUPPORTED_TYPES, label_visibility="collapsed")
    st.caption("Supported: PDF, Word (.docx) and PowerPoint (.pptx). Older .doc and .ppt files: save as .docx or .pptx first.")
    if uploaded and not st.session_state.api_key:
        st.info("Add your Gemini API key in the sidebar to continue.")
    go = st.button("Generate study materials", type="primary", use_container_width=True,
                   disabled=not (uploaded and st.session_state.api_key))
    if go and generate(uploaded, style, n_points, n_quiz, n_cards):
        st.rerun()


# ---------------------------------------------------------------- dashboard
def _clip(text: str, n: int = 150) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "..."


def tile(col, key, title, text, cta, ok=True):
    with col:
        with st.container(key=f"tile_{key}"):
            st.markdown(f"#### {title}")
            st.markdown(f"<div class='tile-text'>{html.escape(text)}</div>", unsafe_allow_html=True)
            if st.button(cta, key=f"open_{key}", type="tertiary", disabled=not ok):
                st.session_state.view = key
                st.rerun()


def overview(data, meta):
    h_left, h_right = st.columns([4, 1.6], vertical_alignment="center")
    h_left.markdown(f"<h1 class='hero'>{html.escape(meta['file'])} is ready</h1>", unsafe_allow_html=True)
    if h_right.button("Upload another file", key="new_file", use_container_width=True):
        st.session_state.data = st.session_state.meta = st.session_state.view = None
        reset_ui_state()
        st.rerun()
    st.caption(f"{meta['size'].capitalize()}. Generated in {meta['seconds']:.0f} s with {meta['model']}. "
               "Pick where to start.")
    for name in meta["errors"]:
        st.warning(f"Could not generate {name.replace('_', ' ')}. Upload the file again to retry.")

    kp, quiz, cards = data.get("key_points"), data.get("quiz"), data.get("flashcards")
    r1, r2 = st.columns(2, gap="medium"), st.columns(2, gap="medium")
    tile(r1[0], "summary", "Summary", _clip(data.get("summary", "Not available.")),
         "Read summary", bool(data.get("summary")))
    tile(r1[1], "points", "Key points",
         f"{len(kp)} points. {_clip(kp[0], 90)}" if kp else "Not available.",
         "Review points", bool(kp))
    tile(r2[0], "quiz", "Quiz",
         f"{len(quiz)} multiple-choice questions with an explanation after each answer."
         if quiz else "Not available.", "Start quiz", bool(quiz))
    tile(r2[1], "cards", "Flashcards",
         f"{len(cards)} cards. Try to answer before you reveal the back."
         if cards else "Not available.", "Study cards", bool(cards))


def detail(view, data, meta):
    if st.button("← Back to overview", key="back", type="tertiary"):
        st.session_state.view = None
        st.rerun()
    stem = Path(meta["file"]).stem
    if view == "summary":
        st.markdown("## Summary")
        st.markdown(data["summary"].replace("$", r"\$"))
        st.download_button("Download summary", data["summary"], file_name=f"{stem}_summary.txt")
    elif view == "points":
        st.markdown("## Key points")
        for p in data["key_points"]:
            st.markdown(f"- {p}")
        st.download_button("Download key points", "\n".join(f"- {p}" for p in data["key_points"]),
                           file_name=f"{stem}_key_points.txt")
    elif view == "quiz":
        st.markdown("## Quiz")
        render_quiz(data["quiz"])
    elif view == "cards":
        st.markdown("## Flashcards")
        render_flashcards(data["flashcards"])


if not st.session_state.data:
    landing()
elif st.session_state.view:
    detail(st.session_state.view, st.session_state.data, st.session_state.meta)
else:
    overview(st.session_state.data, st.session_state.meta)