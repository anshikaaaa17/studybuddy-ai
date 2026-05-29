"""
StudyBuddy AI — app.py
Agentic study assistant: upload lecture PDFs → ask questions, get quizzes, summaries
Voice-enabled via Web Speech API | Agent track | UCWS Singapore Hackathon 2026
"""

import streamlit as st
import streamlit.components.v1 as components
import os
from agent import StudyBuddyAgent

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

# ── Voice component HTML (Web Speech API) ─────────────────────────────────────
VOICE_COMPONENT = """<!DOCTYPE html>
<html>
<head>
<style>
  body { margin: 0; padding: 8px; font-family: sans-serif; background: transparent; }
  #voiceBtn {
    background: #1e3a5f; color: #93c5fd;
    border: 1px solid #3b82f6; padding: 8px 18px;
    border-radius: 8px; font-size: 13px; font-weight: 600;
    cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
  }
  #voiceBtn.listening { background: #7f1d1d; color: #fca5a5; border-color: #ef4444; animation: pulse 1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.6} }
  #status { font-size: 12px; color: #6b7280; margin-left: 8px; }
  #box { margin-top: 8px; padding: 8px 12px; background: #f3f4f6; border-radius: 8px;
         font-size: 13px; color: #111827; border: 1px solid #e5e7eb; display: none; min-height: 32px; }
</style>
</head>
<body>
<button id="voiceBtn" onclick="toggle()">🎤 Click to speak</button>
<span id="status"></span>
<div id="box"></div>
<script>
let rec = null, going = false;
const btn = document.getElementById('voiceBtn');
const st  = document.getElementById('status');
const box = document.getElementById('box');

function toggle() {
  if (!window.SpeechRecognition && !window.webkitSpeechRecognition) {
    st.textContent = '❌ Use Chrome for voice support.'; return;
  }
  going ? rec.stop() : start();
}

function start() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  rec = new SR();
  rec.lang = 'en-US'; rec.interimResults = true; rec.continuous = false;
  rec.onstart = () => {
    going = true;
    btn.textContent = '🔴 Listening... click to stop';
    btn.className = 'listening';
    st.textContent = 'Speak now...';
    box.style.display = 'block'; box.textContent = '...';
  };
  rec.onresult = e => {
    box.textContent = Array.from(e.results).map(r => r[0].transcript).join('');
  };
  rec.onend = () => {
    going = false;
    btn.textContent = '🎤 Click to speak'; btn.className = '';
    const txt = box.textContent;
    if (txt && txt !== '...') {
      navigator.clipboard.writeText(txt)
        .then(() => st.textContent = '✅ Copied! Paste into chat below ↓')
        .catch(() => st.textContent = '✅ Done — paste text above into chat ↓');
    } else { st.textContent = 'No speech. Try again.'; }
  };
  rec.onerror = e => {
    going = false; btn.textContent = '🎤 Click to speak'; btn.className = '';
    st.textContent = e.error === 'not-allowed'
      ? '❌ Mic blocked — allow mic in browser settings.'
      : '❌ ' + e.error;
  };
  rec.start();
}

// TTS listener from parent
window.addEventListener('message', e => {
  if (!e.data || e.data.type !== 'sb_speak') return;
  const text = e.data.text;
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const clean = text.replace(/[#*_`]/g,'').replace(/Source:[^\n]*/g,'').trim().slice(0,600);
  const speak = () => {
    const u = new SpeechSynthesisUtterance(clean);
    u.rate = 0.92; u.lang = 'en-US';
    const vs = speechSynthesis.getVoices();
    const v = vs.find(v=>v.lang.startsWith('en')&&v.localService)||vs.find(v=>v.lang.startsWith('en'))||vs[0];
    if (v) u.voice = v;
    speechSynthesis.speak(u);
  };
  speechSynthesis.getVoices().length ? speak() : (speechSynthesis.onvoiceschanged = speak);
});
</script>
</body>
</html>"""


TTS_SCRIPT = """
<script>
window._sbSpeak = function(text) {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const clean = text
        .replace(/\*\*([^*]+)\*\*/g, '$1')
        .replace(/[#*_`>]/g, '')
        .replace(/Source:[^\n]*/g, '')
        .replace(/[^\x00-\x7F]/g, '')
        .trim().slice(0, 600);
    const doSpeak = () => {
        const utt = new SpeechSynthesisUtterance(clean);
        utt.rate = 0.92; utt.pitch = 1.0; utt.lang = 'en-US';
        const vs = window.speechSynthesis.getVoices();
        const v = vs.find(v => v.lang.startsWith('en') && v.localService)
               || vs.find(v => v.lang.startsWith('en')) || vs[0];
        if (v) utt.voice = v;
        window.speechSynthesis.speak(utt);
    };
    if (window.speechSynthesis.getVoices().length === 0) {
        window.speechSynthesis.onvoiceschanged = doSpeak;
    } else { doSpeak(); }
};
// Legacy alias
window.speakText = window._sbSpeak;
</script>
"""

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

        # Inject TTS script once
        if st.session_state.voice_enabled:
            components.html(TTS_SCRIPT, height=0)

        # Chat history
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Speak last response button
        # Speak last response button
        if st.session_state.voice_enabled and st.session_state.last_response:
            _tc = st.session_state.last_response.replace('"',' ').replace("'", ' ').replace('\n',' ').replace('`','')[:400]
            components.html(
                f'''<button onclick="Array.from(window.parent.document.querySelectorAll('iframe')).forEach(f=>{{try{{f.contentWindow.postMessage({{type:\'sb_speak\',text:\'{_tc}\'}},'*')}}catch(e){{}}}})" '''
                'style="background:#1e3a5f;color:#93c5fd;border:1px solid #3b82f6;padding:6px 16px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:600;">🔊 Read last answer aloud</button>',
                height=50
            )
    if st.session_state.pdf_loaded and st.session_state.mode == "Q&A":

        # Voice input widget
        if st.session_state.voice_enabled:
            components.html(VOICE_COMPONENT, height=120)
            st.caption("💡 After speaking, your transcription is auto-copied — paste it into the chat box below.")

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
                # Auto-speak via iframe postMessage (st.markdown strips scripts)
                if st.session_state.voice_enabled:
                    escaped = response.replace("'", " ").replace('"', ' ').replace("\n", " ").replace("`", "")[:500]
                    components.html(
                        f"""<script>
                        Array.from(window.parent.document.querySelectorAll('iframe')).forEach(f=>{{
                            try{{f.contentWindow.postMessage({{type:'sb_speak',text:'{escaped}'}},'*')}}catch(e){{}}
                        }});
                        </script>""",
                        height=0,
                    )
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.session_state.last_response = response

    # ── Quiz mode ─────────────────────────────────────────────────────────────
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
                st.markdown("---\n**🎤 Voice tips:**\n- Click the mic button\n- Speak clearly\n- Answer auto-reads after response")
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
