import re
import math
import json
import time
import urllib.request
import urllib.error
from collections import defaultdict
import fitz  # PyMuPDF

CHUNK_SIZE    = 600
CHUNK_OVERLAP = 100
TOP_K         = 5

# ── Demo-safe model list ──────────────────────────────────────────────────────
# Order: fastest/newest first, older models as fallbacks.
# gemini-2.0-flash-lite has very high RPM — ideal last-resort fallback.
GEMINI_MODELS = [
    "gemini-2.0-flash",        # primary: fast, free tier 1500 req/day
    "gemini-2.0-flash-lite",   # fallback 1: lighter, higher quota headroom
    "gemini-1.5-flash",        # fallback 2: proven stable
]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

# ── Multi-key pool ────────────────────────────────────────────────────────────
# Load extra demo keys from Streamlit secrets (GEMINI_API_KEY_2, _3, etc.)
# Falls back gracefully if secrets not available (local dev).
def _load_key_pool(primary_key: str) -> list:
    """Return deduplicated list of API keys: primary first, then extras from secrets."""
    keys = [primary_key] if primary_key else []
    try:
        import streamlit as st
        for i in range(2, 8):  # looks for GEMINI_API_KEY_2 through _7
            k = st.secrets.get(f"GEMINI_API_KEY_{i}", "")
            if k and k not in keys:
                keys.append(k)
    except Exception:
        pass
    return keys


# ────── Lightweight TF-IDF vector store ──────────────────────────────────────────────────────────

class TFIDFVectorStore:
    def __init__(self):
        self.chunks = []
        self.vecs   = []
        self.idf    = {}

    def _tok(self, text):
        return re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())

    def _tf(self, tokens):
        c = defaultdict(int)
        for t in tokens: c[t] += 1
        n = max(len(tokens), 1)
        return {t: v/n for t, v in c.items()}

    def add(self, chunks):
        self.chunks = chunks
        all_tf, df  = [], defaultdict(int)
        for ch in chunks:
            t = self._tf(self._tok(ch))
            all_tf.append(t)
            for k in t: df[k] += 1
        N = len(chunks)
        self.idf  = {k: math.log((N+1)/(v+1))+1 for k, v in df.items()}
        self.vecs = [{k: v*self.idf.get(k,1) for k,v in t.items()} for t in all_tf]

    def query(self, q, k=TOP_K):
        qt  = self._tf(self._tok(q))
        qv  = {k: v*self.idf.get(k,1) for k,v in qt.items()}
        def cos(a, b):
            common = set(a) & set(b)
            dot = sum(a[x]*b[x] for x in common)
            ma  = math.sqrt(sum(v*v for v in a.values()))
            mb  = math.sqrt(sum(v*v for v in b.values()))
            return dot/(ma*mb) if ma and mb else 0
        scores = sorted(enumerate(self.vecs), key=lambda x: cos(qv, x[1]), reverse=True)
        return [self.chunks[i] for i, _ in scores[:min(k, len(self.chunks))]]


# ────── Gemini API — key pool × model fallback + exponential backoff ─────────────────────────────
# Supports TWO key formats:
#   AIzaSy...  → standard REST API key, sent as ?key= query param
#   AQ....     → OAuth2 bearer token (new AI Studio format), sent as Authorization: Bearer header
# Strategy: outer loop = keys, inner loop = models. On daily quota, move to next KEY.

GEMINI_URL_BEARER = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

def _make_request(model: str, key: str, data: bytes) -> urllib.request.Request:
    """Build request supporting both AIzaSy (query param) and AQ. (Bearer token) key formats."""
    if key.startswith("AIza"):
        url     = GEMINI_URL.format(model=model, key=key)
        headers = {"Content-Type": "application/json"}
    else:
        # AQ. / OAuth2 token — must use Authorization: Bearer header
        url     = GEMINI_URL_BEARER.format(model=model)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    return urllib.request.Request(url, data=data, headers=headers, method="POST")


def call_gemini(api_key: str, system: str, user: str, max_tokens: int = 1000) -> str:
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents":           [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig":   {"maxOutputTokens": max_tokens, "temperature": 0.2}
    }
    key_pool   = _load_key_pool(api_key)
    last_error = "no keys configured"

    for key in key_pool:
        for model in GEMINI_MODELS:
            data = json.dumps(payload).encode("utf-8")
            req  = _make_request(model, key, data)
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=40) as resp:
                        result = json.loads(resp.read().decode())
                        return result["candidates"][0]["content"]["parts"][0]["text"]
                except urllib.error.HTTPError as e:
                    body = e.read().decode()
                    if e.code == 404:
                        last_error = f"[{model}] not found on this key"
                        break  # try next model (same key)
                    if e.code == 429:
                        is_daily = (
                            "PerDay" in body
                            or "per_day" in body.lower()
                            or "quota" in body.lower()
                            or "RESOURCE_EXHAUSTED" in body
                        )
                        if is_daily:
                            last_error = f"[key …{key[-4:]}][{model}] daily quota exceeded"
                            break  # exhausted this model on this key; try next model
                        # Per-minute rate limit — wait and retry
                        time.sleep(4 * (2 ** attempt))
                        continue
                    if e.code == 503 and attempt < 2:
                        time.sleep(4 * (2 ** attempt))
                        continue
                    raise RuntimeError(f"Gemini API error {e.code}: {body[:200]}") from e
        # All models exhausted on this key → try next key in pool

    raise RuntimeError(
        f"All API keys and models exhausted. Last error: {last_error}\n"
        "Add GEMINI_API_KEY_2 / _3 in Streamlit secrets, or wait until midnight UTC."
    )


# ────── Main agent class ────────────────────────────────────────────────────────────────────────

class StudyBuddyAgent:

    # Admin content patterns — chunks matching these are excluded from index
    ADMIN_PATTERNS = re.compile(
        r'(office hours|email:|@ntu\.edu\.sg|@e\.ntu|tutorial schedule|'
        r'lecture schedule|course outline|grading|assessment breakdown|'
        r'recommended textbook|course coordinator|guest lecture|'
        r'late submission|academic integrity|plagiarism|'
        r'course code|prerequisites|sc\d{4}|ce\d{4}|cz\d{4})',
        re.IGNORECASE
    )

    # Admin keywords for page-level filtering (consistent with _strip_admin_pages)
    ADMIN_KEYWORDS = [
        'office hours','email:','tutorial schedule','lecture schedule',
        'course outline','grading','assessment','textbook','recommended reading',
        'course coordinator','instructor','professor','guest lecture',
        'attendance','plagiarism','academic integrity','late submission',
        'course code','prerequisites','learning outcomes','nanyang','ntu','semester'
    ]

    def __init__(self, api_key: str):
        self.api_key      = api_key
        self.store        = TFIDFVectorStore()
        self.doc_text     = ""
        self.total_chunks = 0

    # ────── Ingestion ──────────────────────────────────────────────────────────────────────────

    def _is_admin_chunk(self, chunk: str) -> bool:
        hits = len(self.ADMIN_PATTERNS.findall(chunk))
        return hits >= 2 and len(chunk) < 700

    def _is_admin_page(self, text: str) -> bool:
        """Check if a full page should be filtered as admin content.
        
        Uses same logic as _strip_admin_pages() for consistency:
        - Count admin keywords
        - Filter if 3+ keywords AND page < 800 chars
        """
        body = text.lower()
        hits = sum(1 for kw in self.ADMIN_KEYWORDS if kw in body)
        return hits >= 3 and len(text.strip()) < 800

    def ingest_pdf(self, uploaded_file) -> int:
        pdf_bytes = uploaded_file.read()
        doc       = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages     = []
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                # Strip stray markdown from PDF extraction
                text = re.sub(r'\*{1,2}', '', text)
                text = re.sub(r'_{1,2}', '', text)
                pages.append(f"[Page {i+1}]\n{text}")
        self.doc_text = "\n\n".join(pages)
        all_chunks    = self._chunk(self.doc_text)
        clean         = [c for c in all_chunks if not self._is_admin_chunk(c)]
        self.store.add(clean)
        self.total_chunks = len(clean)
        return len(clean)

    def _chunk(self, text):
        chunks, start = [], 0
        while start < len(text):
            end = start + CHUNK_SIZE
            if end < len(text):
                lb = text[max(start, end-80):end]
                bp = max(lb.rfind('\n'), lb.rfind('. '), lb.rfind(' '))
                if bp != -1:
                    end = max(start, end-80) + bp + 1
            ch = text[start:end].strip()
            if ch:
                chunks.append(ch)
            start = end - CHUNK_OVERLAP
        return chunks

    # ────── Retrieval ──────────────────────────────────────────────────────────────────────────

    def retrieve(self, query, k=TOP_K):
        return "\n\n---\n\n".join(self.store.query(query, k=k))

    def retrieve_conceptual(self, k=8) -> str:
        """Pull chunks most likely to contain testable academic content."""
        queries = [
            "definition algorithm model method technique",
            "theory concept principle formula equation",
            "classification regression neural network learning",
            "how does process step function work",
        ]
        seen, results = set(), []
        for q in queries:
            for chunk in self.store.query(q, k=3):
                if chunk not in seen and not self._is_admin_chunk(chunk):
                    seen.add(chunk)
                    results.append(chunk)
            if len(results) >= k:
                break
        return "\n\n---\n\n".join(results[:k])

    # ────── Q&A ────────────────────────────────────────────────────────────────────────────────

    def summarise_by_slide(self) -> str:
        """FIX #3: Use _is_admin_page() for consistent filtering across full pages."""
        parts = re.split(r'(\[Page \d+\])', self.doc_text)
        pages = []
        i = 0
        while i < len(parts):
            if re.match(r'\[Page \d+\]', parts[i]) and i+1 < len(parts):
                num  = int(re.search(r'\d+', parts[i]).group())
                text = parts[i+1].strip()
                # FIX: Use _is_admin_page(text) instead of _is_admin_chunk(text[:700])
                if text and not self._is_admin_page(text):
                    pages.append((num, text))
                i += 2
            else:
                i += 1
        if not pages:
            return "No content pages found after filtering admin slides."
        combined = "".join(f"[Page {n}]\n{t[:300]}\n\n" for n, t in pages[:20])
        system = """You are StudyBuddy AI. For each page, write ONE bullet with its real page number.
Format: • **Page N:** [one sentence — key concept on this slide]
Skip admin slides. One line per slide only."""
        result = call_gemini(self.api_key, system, combined, max_tokens=1500)
        if len(pages) > 20:
            result += f"\n\n*Showing first 20 of {len(pages)} content pages.*"
        return result

    def answer_question(self, question: str) -> str:
        # Route slide-by-slide requests
        if any(p in question.lower() for p in
               ["slide by slide", "slide-by-slide", "page by page", "each slide", "each page"]):
            return self.summarise_by_slide()

        # Handle filtered page range requests gracefully
        page_req = re.search(r'(?:slide|page)s?\s*([\d]+)\s*(?:-|to)\s*([\d]+)', question.lower())
        if page_req:
            lo, hi = int(page_req.group(1)), int(page_req.group(2))
            available = sorted(set(int(p) for p in re.findall(r'\[Page (\d+)\]', self.doc_text)))
            if available and hi < available[0]:
                return (
                    f"**Pages {lo}–{hi} were filtered out** — they contained course admin content "
                    f"(cover page, instructor info, schedule) rather than lecture material.\n\n"
                    f"First content page available: **Page {available[0]}**\n\n"
                    f"Try asking about a topic instead, e.g. *'What is NLP?'*"
                )

        ctx    = self.retrieve(question)
        system = """You are StudyBuddy AI, an expert study assistant.

RULES:
1. Answer ONLY from the provided lecture context. Never hallucinate.
2. Go straight to the answer — no greeting, no preamble.
3. Only greet if the message is ONLY "hi" or "hello" with nothing else.
4. For analogies/simple explanations: use context facts with real-world metaphors.
5. If not in the slides, say so honestly.

FORMAT:
- Direct answer first.
- Key concepts in **bold**.
- Bullet points for lists.
- End with: 📖 Source: [page or slide reference]"""
        user = f"Context:\n{ctx}\n\nQuestion: {question}"
        return call_gemini(self.api_key, system, user, max_tokens=1500)

    # ────── Quiz ────────────────────────────────────────────────────────────────────────────────

    def _validate_quiz(self, text: str) -> bool:
        q_count = len(re.findall(r'\*\*Q[1-5]\.', text))
        if q_count < 5:
            return False
        for q in re.split(r'\*\*Q[1-5]\.', text)[1:]:
            if not re.search(r'D\)', q):
                return False
        return True

    def generate_quiz(self) -> str:
        ctx    = self.retrieve_conceptual(k=8)
        system = """You are StudyBuddy AI generating a multiple-choice quiz.

STRICT RULES:
- Output EXACTLY 5 complete questions. Never stop before Q5.
- ONLY test concepts, theory, algorithms, definitions — NEVER admin info, emails, names, dates.
- Every question MUST have A) B) C) D) each on its own line.
- Never cut off. D) must always appear.

FORMAT:
**Q1. [question]**
A) [option]
B) [option]
C) [option]
D) [option]
*(Answer: X — one sentence reason)*

Difficulty: Q1-Q2 easy, Q3-Q4 medium, Q5 hard."""

        for attempt in range(2):
            extra = "" if attempt == 0 else f"\n\n[Attempt {attempt+1}: output ALL 5 questions with A B C D each.]"
            try:
                result = call_gemini(
                    self.api_key, system,
                    f"Generate all 5 questions from:\n\n{ctx}{extra}",
                    max_tokens=2000
                )
                if self._validate_quiz(result):
                    return result
            except RuntimeError:
                if attempt == 1:
                    return "⚠️ Quiz generation failed. Please check your API quota and try again."
        
        if not self._validate_quiz(result):
            result += "\n\n---\n⚠️ *Quiz may be incomplete. Click Generate again for a fresh quiz.*"
        return result

    def check_answer(self, student_answer: str, context: str) -> str:
        system = """You are StudyBuddy AI checking a quiz answer.
State: ✅ Correct! or ❌ Incorrect.
Brief explanation + correct answer if wrong + tip to remember it.
End with: Topic: [2-3 word concept]
Be encouraging. Max 4 sentences."""
        return call_gemini(
            self.api_key, system,
            f"Question:\n{context}\n\nStudent answered: {student_answer}",
            max_tokens=250
        )

    def extract_topic(self, response: str):
        m = re.search(r'Topic:\s*\[?([\ w\s\-]+)\]?', response, re.IGNORECASE)
        return m.group(1).strip() if m else "General Review"

    # ────── Summary ────────────────────────────────────────────────────────────────────────────

    def summarise(self) -> str:
        clean  = self._strip_admin_pages(self.doc_text)
        excerpt = clean[:6000]
        if len(clean) > 6000:
            excerpt += "\n\n[... document continues ...]"
        system = """You are StudyBuddy AI creating exam-focused study notes.

CRITICAL:
- Technical/academic content ONLY — concepts, theories, algorithms, models.
- IGNORE and DO NOT MENTION: instructor names, emails, schedules, textbooks, course codes, grading, admin.
- Use clean markdown. Always close ** bold tags.

Structure:
## Key Topics
[3-6 bullets — technical subjects only]

## Core Concepts
[**Concept**: one-sentence definition each]

## Quick Revision Points
[5-7 bullets — most important exam facts]

## Likely Exam Questions
1. [question]
2. [question]
3. [question]

---
*Ask "summarise slide by slide" for a page-by-page breakdown.*"""
        return call_gemini(
            self.api_key, system,
            f"Summarise — technical content only, ignore admin:\n\n{excerpt}",
            max_tokens=1200
        )

    def _strip_admin_pages(self, text: str) -> str:
        """Filter admin pages using ADMIN_KEYWORDS for consistency."""
        pages  = re.split(r'(\[Page \d+\])', text)
        result = []
        i = 0
        while i < len(pages):
            if re.match(r'\[Page \d+\]', pages[i]) and i+1 < len(pages):
                body = pages[i+1].lower()
                hits = sum(1 for kw in self.ADMIN_KEYWORDS if kw in body)
                # FIX #3: Consistent threshold (3+ keywords, <800 chars)
                if hits >= 3 and len(pages[i+1].strip()) < 800:
                    i += 2
                    continue
                result.append(pages[i] + pages[i+1])
                i += 2
            else:
                result.append(pages[i])
                i += 1
        return ''.join(result)
