# StudyBuddy AI 📚

> **Drop your lecture slides. Get answers, quizzes, and smart summaries — instantly.**

An agentic study assistant built for the **UCWS Singapore Hackathon 2026 · Agent Track**.

---

## What it does

| Mode | What happens |
|------|-------------|
| **Q&A** | Ask anything → agent retrieves relevant slides → Gemini answers with citations |
| **Quiz** | Agent generates 5 MCQs → shows one at a time → tracks weak topics |
| **Summary** | Structured revision notes with key concepts and likely exam questions |
| **Voice** | Speak your question → answer read aloud (Chrome, HTTPS) |

## How the agent works

```
User question
    → Think: what do I need to answer this?
    → Tool: TF-IDF search over PDF chunks (no external DB)
    → Observe: read retrieved context
    → Generate: Gemini reasons over context → grounded, cited answer
```

This is a **RAG agent** — not a generic chatbot. Every answer is grounded in your slides.

---

## Quick start

### 1. Clone & install

```bash
git clone https://github.com/anshikaaaa17/studybuddy-ai
cd studybuddy-ai
pip install -r requirements.txt
```

### 2. Get your free Google AI API key

1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Sign in → **Get API key** → **Create API key**
3. Copy the key (starts with `AIza...`)

### 3. Run locally

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501), paste your key, upload a PDF.

---

## Deploy free (Streamlit Cloud)

1. Push repo to GitHub (public)
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect repo → main file: `app.py` → Deploy
4. In Settings → Secrets, add: `GEMINI_API_KEY = "your_key"`

---

## Tech stack

| Layer | Tool |
|-------|------|
| Language | Python 3.8+ |
| UI | Streamlit |
| PDF parsing | PyMuPDF |
| Vector store | Custom TF-IDF (stdlib only) |
| AI reasoning | Google Gemini API (2.0 Flash, free tier) |
| Voice | Web Speech API (browser built-in) |
| Hosting | Streamlit Community Cloud |

**Only 2 pip dependencies** — `streamlit` and `pymupdf`.

---

## Project structure

```
studybuddy-ai/
├── app.py        # Streamlit UI — all modes + voice
├── agent.py      # RAG agent: ingest, retrieve, reason
├── requirements.txt
└── README.md
```

---

## Built by

**Anshika Uppal** · NTU Computer Science · Singapore  
[LinkedIn](https://linkedin.com/in/uppalanshika/) · [GitHub](https://github.com/anshikaaaa17)

UCWS Singapore Hackathon 2026 · Agent Track · Organised by Epic Connector & Canlah.AI
