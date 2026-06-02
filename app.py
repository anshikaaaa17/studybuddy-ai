"""
StudyBuddy AI — app.py
Agentic study assistant: upload lecture PDFs → ask questions, get quizzes, summaries
Voice-enabled via Web Speech API | Agent track | UCWS Singapore Hackathon 2026
"""

import streamlit as st
import streamlit.components.v1 as components
import os
import io
from agent import StudyBuddyAgent

def tts_audio_bytes(text: str) -> bytes | None:
    """Convert text to MP3 bytes via gTTS. Returns None if gTTS unavailable."""
    try:
        from gtts import gTTS
        clean = (text
                 .replace("**", "").replace("*", "").replace("#", "")
                 .replace("`", "").replace(">", ""))
        # Strip source citations
        import re
        clean = re.sub(r'Source:[^\n]*', '', clean).strip()[:800]
        buf = io.BytesIO()
        gTTS(text=clean, lang="en", slow=False).write_to_fp(buf)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        st.error(f"TTS error: {e}")
        return None

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="StudyBuddy AI",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    div.stButton > button {
        background: #2563eb !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        border: none !important;
    }
    div.stButton > button:hover { background: #1d4ed8 !important; }
    .mode-badge {
        display: inline-block; padding: 4px 14px;
        border-radius: 20px; font-size: 11px;
        font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.06em; margin-bottom: 14px;
    }
    .badge-qa   { background:#1e3a5f; color:#93c5fd; border:1px solid #3b82f6; }
    .badge-quiz { background:#2e1f55; color:#c4b5fd; border:1px solid #8b5cf6; }
    .badge-sum  { background:#14392b; color:#6ee7b7; border:1px solid #10b981; }
    .weak-tag {
        display:inline-block; margin:2px 3px; padding:3px 10px;
        border-radius:12px; background:#3b1c1c; color:#fca5a5;
        font-size:12px; font-weight:500; border:1px solid #7f1d1d;
    }
    /* Voice button styling */
    .voice-btn {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 8px 18px; border-radius: 8px; font-size: 13px;
        font-weight: 600; cursor: pointer; border: none;
        transition: all 0.2s;
    }
    .voice-idle    { background: #1e3a5f; color: #93c5fd; }
    .voice-listen  { background: #7f1d1d; color: #fca5a5; animation: pulse 1s infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.6} }
</style>
""", unsafe_allow_html=True)







# ── Session state ─────────────────────────────────────────────────────────────
for key, default in {
    "agent": None, "messages": [], "mode": "Q&A",
    "pdf_loaded": False, "pdf_name": None,
    "weak_topics": [], "quiz_score": {"correct": 0, "total": 0},
    "voice_enabled": False, "last_response": ""
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📚 StudyBuddy AI")
    st.caption("Your AI-powered study assistant")
    st.divider()

    # API key with secrets fallback
    secret_key = ""
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        pass

    api_key = st.text_input(
        "Google AI API Key",
        type="password",
        placeholder="Using cloud secret ✓" if secret_key else "AIzaSy...",
        help="Free key at aistudio.google.com → Get API key",
    )
    api_key = api_key or secret_key
    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key

    st.divider()
    st.markdown("### 📄 Upload PDF")
    uploaded_file = st.file_uploader(
        "Drop your lecture slides here",
        type=["pdf"],
        help="Max 50MB. Any NTU lecture PDF works."
    )

    if uploaded_file and api_key:
        if uploaded_file.name != st.session_state.pdf_name:
            with st.spinner("Reading and indexing your slides..."):
                try:
                    uploaded_file.seek(0)
                    agent = StudyBuddyAgent(api_key=api_key)
                    chunk_count = agent.ingest_pdf(uploaded_file)
                    st.session_state.agent       = agent
                    st.session_state.pdf_loaded  = True
                    st.session_state.pdf_name    = uploaded_file.name
                    st.session_state.messages    = []
                    st.session_state.weak_topics = []
                    st.session_state.quiz_score  = {"correct": 0, "total": 0}
                    st.success(f"✅ Loaded! {chunk_count} chunks indexed.")
                except Exception as e:
                    st.error(f"Error: {e}")
    elif uploaded_file and not api_key:
        st.warning("⚠️ Enter your API key first.")

    st.divider()
    st.markdown("### 🎛️ Mode")
    mode = st.radio(
        "Choose what to do",
        ["Q&A", "Quiz", "Summary"],
        index=["Q&A", "Quiz", "Summary"].index(st.session_state.mode),
    )
    st.session_state.mode = mode

    st.divider()

    # Voice toggle
    st.markdown("### 🎤 Voice")
    voice_on = st.toggle("Enable voice input + speech", value=st.session_state.voice_enabled)
    st.session_state.voice_enabled = voice_on
    if voice_on:
        st.caption("Chrome recommended. Click 🎤 in chat to speak, answers read aloud.")

    st.divider()

    if st.session_state.pdf_loaded:
        st.markdown("### 📊 Quiz Stats")
        c1, c2 = st.columns(2)
        c1.metric("✅ Correct", st.session_state.quiz_score["correct"])
        c2.metric("📝 Total",   st.session_state.quiz_score["total"])
        if st.session_state.weak_topics:
            st.markdown("**Weak topics:**")
            html = " ".join(f'<span class="weak-tag">{t}</span>'
                            for t in st.session_state.weak_topics[-6:])
            st.markdown(html, unsafe_allow_html=True)

    if st.button("🗑️ Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.last_response = ""
        st.rerun()

    st.divider()
    st.caption("UCWS Singapore Hackathon 2026 · Agent Track")

# ── Main area ─────────────────────────────────────────────────────────────────
col_main, col_tips = st.columns([3, 1])

with col_main:

    # ── Welcome ───────────────────────────────────────────────────────────────
    if not st.session_state.pdf_loaded:
        st.markdown("## 👋 Welcome to StudyBuddy AI")
        st.markdown("Upload a lecture PDF and enter your Google AI key to get started.")
        st.info(
            "**How it works:**\n\n"
            "1. 📄 Upload any lecture PDF — agent reads and indexes all content locally\n\n"
            "2. 💬 **Q&A** — ask anything, agent retrieves relevant slides and answers with citations\n\n"
            "3. 🧪 **Quiz** — agent generates 5 MCQs from your slides, tracks weak topics\n\n"
            "4. 📝 **Summary** — structured revision notes with likely exam questions\n\n"
            "5. 🎤 **Voice** — speak your question, hear the answer read aloud (toggle in sidebar)"
        )
        c1, c2, c3 = st.columns(3)
        c1.success("**1. Retrieve**\nSearches PDF chunks with TF-IDF to find relevant content")
        c2.info("**2. Reason**\nGemini 2.5 Flash reasons over retrieved context")
        c3.warning("**3. Respond**\nCited, grounded answer — no hallucination")

    # ── Active session ────────────────────────────────────────────────────────
    else:
        badge_map = {
            "Q&A":     ("badge-qa",   "💬 Q&A"),
            "Quiz":    ("badge-quiz", "🧪 Quiz"),
            "Summary": ("badge-sum",  "📝 Summary"),
        }
        cls, label = badge_map[st.session_state.mode]
        voice_indicator = " 🎤" if st.session_state.voice_enabled else ""
        st.markdown(f'<span class="mode-badge {cls}">{label} Mode{voice_indicator}</span>',
                    unsafe_allow_html=True)
        st.caption(f"Loaded: **{st.session_state.pdf_name}**")

        # Chat history
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Read last answer aloud via gTTS
        if st.session_state.voice_enabled and st.session_state.last_response:
            if st.button("🔊 Read last answer aloud"):
                audio = tts_audio_bytes(st.session_state.last_response)
                if audio:
                    st.audio(audio, format="audio/mp3", autoplay=True)
                else:
                    st.warning("Install gTTS: `pip install gTTS`")
    if st.session_state.pdf_loaded and st.session_state.mode == "Q&A":

        # Voice input widget - self contained mic + TTS
        if st.session_state.voice_enabled:
            components.html("""<!DOCTYPE html><html><head><style>
  body{margin:0;padding:8px;font-family:sans-serif;background:transparent}
  .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:6px}
  button{padding:7px 14px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid}
  #m{background:#1e3a5f;color:#93c5fd;border-color:#3b82f6}
  #m.on{background:#7f1d1d;color:#fca5a5;border-color:#ef4444}
  #st{font-size:12px;color:#6b7280;margin-top:4px}
  #box{margin-top:6px;padding:8px;background:#f3f4f6;border-radius:8px;font-size:13px;color:#111;display:none}
</style></head><body>
<div class="row">
  <button id="m" onclick="tog()">🎤 Speak</button>
</div>
<div id="st"></div>
<div id="box"></div>
<script>
var rec=null,going=false;
var m=document.getElementById('m'),st=document.getElementById('st'),box=document.getElementById('box');
function tog(){going?rec.stop():go()}
function go(){
  if(!window.SpeechRecognition&&!window.webkitSpeechRecognition){st.textContent='❌ Use Chrome';return}
  var SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  rec=new SR();rec.lang='en-US';rec.interimResults=true;
  rec.onstart=function(){going=true;m.textContent='🔴 Stop';m.className='on';st.textContent='Listening...';box.style.display='block';box.textContent='...'};
  rec.onresult=function(e){box.textContent=Array.from(e.results).map(function(r){return r[0].transcript}).join('')};
  rec.onend=function(){going=false;m.textContent='🎤 Speak';m.className='';var t=box.textContent;
    if(t&&t!='...'){navigator.clipboard.writeText(t).then(function(){st.textContent='✅ Copied — paste into chat below ↓'}).catch(function(){st.textContent='✅ Transcribed — paste above into chat ↓'})}else{st.textContent='No speech detected'}};
  rec.onerror=function(e){going=false;m.textContent='🎤 Speak';m.className='';st.textContent=e.error==='not-allowed'?'❌ Allow mic in browser settings':'❌ '+e.error};
  rec.start();
}
</script></body></html>""", height=90)
            st.caption("💡 Speak → transcript auto-copied → paste into chat below. Use 🔊 button above to hear last answer.")

        prompt = st.chat_input("Ask anything about your slides...")
        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    try:
                        response = st.session_state.agent.answer_question(prompt)
                    except RuntimeError as e:
                        err = str(e)
                        if "quota exhausted" in err.lower() or "429" in err:
                            response = (
                                "⚠️ **Gemini API daily quota reached.**\n\n"
                                "Free tier allows ~20 requests/day on gemini-2.5-flash and "
                                "1,500/day on gemini-2.0-flash.\n\n"
                                "**Options:**\n"
                                "- Wait until tomorrow (resets at midnight UTC)\n"
                                "- Create a new Google AI API key at [aistudio.google.com](https://aistudio.google.com)\n"
                                "- Add billing to your Google AI account for higher limits"
                            )
                        else:
                            response = f"❌ Error: {err}"
                st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.session_state.last_response = response
    elif st.session_state.pdf_loaded and st.session_state.mode == "Quiz":
        import re as _re

        def parse_questions(quiz_text):
            parts = _re.split(r'(?=\*\*Q\d+\.)', quiz_text.strip())
            return [p.strip() for p in parts if p.strip() and _re.match(r'\*\*Q\d+\.', p)]

        def strip_answer_from_question(question_text):
            """Remove the answer line from question text for display to user.
            Keeps the full question with answer available for checking.
            Example: "**Q1. ...\\nA) ...\\nB) ...\\nC) ...\\nD) ...\\n*(Answer: B – reason)*"
            Returns: "**Q1. ...\\nA) ...\\nB) ...\\nC) ...\\nD) ..."
            """
            lines = question_text.split('\n')
            while lines and lines[-1].strip().startswith('*(Answer:'):
                lines.pop()
            return '\n'.join(lines)

        # Init quiz state
        if "quiz_questions" not in st.session_state:
            st.session_state.quiz_questions = []
            st.session_state.quiz_idx = 0
            st.session_state.quiz_answered = []

        if st.button("🎲 Generate new quiz (5 questions)", use_container_width=True):
            st.session_state.messages = []
            st.session_state.quiz_questions = []
            st.session_state.quiz_idx = 0
            st.session_state.quiz_answered = []
            with st.spinner("Generating quiz from your slides..."):
                quiz = st.session_state.agent.generate_quiz()
            qs = parse_questions(quiz)
            if qs:
                st.session_state.quiz_questions = qs
                st.session_state.quiz_score["total"] += 5
            else:
                st.session_state.messages.append({"role": "assistant", "content": quiz})
            st.rerun()

        questions = st.session_state.get("quiz_questions", [])
        idx = st.session_state.get("quiz_idx", 0)

        if questions:
            total_q = len(questions)
            # Show previous answered pairs
            for pair in st.session_state.get("quiz_answered", []):
                with st.chat_message("user"):
                    st.markdown(pair["answer"])
                with st.chat_message("assistant"):
                    st.markdown(pair["feedback"])
            # Show current question
            if idx < total_q:
                st.markdown(f"**Question {idx+1} of {total_q}**")
                with st.chat_message("assistant"):
                    # Display question WITHOUT the answer
                    st.markdown(strip_answer_from_question(questions[idx]))
            else:
                st.success("🎉 Quiz complete! Click Generate for a new quiz.")
        else:
            # Fallback: show all in messages
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        answer = st.chat_input("Type A, B, C or D...")
        if answer and questions and idx < len(questions):
            with st.spinner("Checking..."):
                response = st.session_state.agent.check_answer(answer, questions[idx])
            if "quiz_answered" not in st.session_state:
                st.session_state.quiz_answered = []
            st.session_state.quiz_answered.append({"answer": answer, "feedback": response})
            st.session_state.quiz_idx += 1
            st.session_state.last_response = response
            if "correct" in response.lower() and "incorrect" not in response.lower():
                st.session_state.quiz_score["correct"] += 1
            else:
                topic = st.session_state.agent.extract_topic(response)
                if topic and topic not in st.session_state.weak_topics:
                    st.session_state.weak_topics.append(topic)
            st.rerun()

    # ── Summary mode ──────────────────────────────────────────────────────────
    elif st.session_state.pdf_loaded and st.session_state.mode == "Summary":
        if st.button("📄 Generate full summary", use_container_width=True):
            with st.spinner("Summarising your slides..."):
                summary = st.session_state.agent.summarise()
            st.session_state.messages.append({"role": "assistant", "content": summary})
            with st.chat_message("assistant"):
                st.markdown(summary)

        prompt = st.chat_input("Ask for a section summary, or type 'summarise slide by slide'...")
        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Summarising..."):
                    response = st.session_state.agent.answer_question(
                        f"Summarise the content related to: {prompt}"
                    )
                st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})

# ── Tips panel ────────────────────────────────────────────────────────────────
with col_tips:
    if st.session_state.pdf_loaded:
        st.markdown("### 💡 Tips")
        if st.session_state.mode == "Q&A":
            st.markdown(
                "Try asking:\n"
                "- *What is this lecture about?*\n"
                "- *Explain gradient descent simply*\n"
                "- *Compare X and Y*\n"
                "- *Give me a layman example of NLP*"
            )
            if st.session_state.voice_enabled:
                st.markdown("---\n**🎤 Voice tips:**\n- Click the mic button\n- Speak clearly\n- Paste transcript into chat\n- Use 🔊 Read last answer aloud")
        elif st.session_state.mode == "Quiz":
            st.markdown(
                "- Click Generate for 5 MCQs\n"
                "- Type A, B, C or D\n"
                "- Weak topics tracked automatically\n"
                "- Generate again for new questions"
            )
        elif st.session_state.mode == "Summary":
            st.markdown(
                "- Click Generate for full notes\n"
                "- Or type: *summarise slide by slide*\n"
                "- Ask: *Summarise neural networks*"
            )

        st.markdown("---")
        st.markdown("### 🔍 Agent steps")
        st.markdown(
            "1. **Retrieve** relevant chunks\n"
            "2. **Reason** with Gemini 2.5\n"
            "3. **Return** grounded answer"
        )
