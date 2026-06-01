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
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"]
GEMINI_URL    = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


# ── Lightweight TF-IDF vector store ──────────────────────────────────────────

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


# ── Gemini API — multi-key rotation + model fallback ─────────────────────────

def _get_keys(primary_key: str) -> list:
    """Load all keys from Streamlit secrets — handles both naming styles:
    GEMINI_API_KEY1 / GEMINI_API_KEY2 (no underscore)
    GEMINI_API_KEY_2 / GEMINI_API_KEY_3 (with underscore)
    """
    keys = [primary_key] if primary_key else []
    try:
        import streamlit as st
        # Style 1: GEMINI_API_KEY1, GEMINI_API_KEY2 ... (no underscore)
        for i in range(1, 8):
            k = st.secrets.get(f"GEMINI_API_KEY{i}", "")
            if k and k not in keys:
                keys.append(k)
        # Style 2: GEMINI_API_KEY_2, GEMINI_API_KEY_3 ... (with underscore)
        for i in range(2, 8):
            k = st.secrets.get(f"GEMINI_API_KEY_{i}", "")
            if k and k not in keys:
                keys.append(k)
    except Exception:
        pass
    return [k for k in keys if k and len(k) > 10]


def call_gemini(api_key: str, system: str, user: str, max_tokens: int = 1000) -> str:
    """Try all keys across all models. Keys rotated on quota exhaustion."""
    payload = json.dumps({
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2}
    }).encode("utf-8")

    keys = _get_keys(api_key)
    last_error = None

    for key in keys:
        for model in GEMINI_MODELS:
            url      = GEMINI_URL.format(model=model)
            # Both AIza and AQ. keys use ?key= query param (NOT Bearer)
            full_url = url + f"?key={key}"
            headers  = {"Content-Type": "application/json"}
            req      = urllib.request.Request(
                full_url, data=payload, headers=headers, method="POST"
            )
            for attempt in range(2):
                try:
                    with urllib.request.urlopen(req, timeout=40) as resp:
                        result = json.loads(resp.read().decode())
                        return result["candidates"][0]["content"]["parts"][0]["text"]
                except urllib.error.HTTPError as e:
                    body = e.read().decode()
                    if e.code == 404:
                        last_error = f"[{model}] not found"
                        break  # next model
                    if e.code == 429:
                        if "PerDay" in body or "quota" in body.lower():
                            last_error = f"[{key[:12]}../{model}] quota exceeded"
                            break  # next model (try next key)
                        time.sleep(4 * (2 ** attempt))
                        continue
                    if e.code in [400, 401, 403]:
                        last_error = f"[{key[:12]}..] auth error: {body[:80]}"
                        break  # next model
                    if e.code == 503 and attempt < 1:
                        time.sleep(4)
                        continue
                    last_error = f"[{model}] HTTP {e.code}: {body[:60]}"
                    break
                except Exception as ex:
                    last_error = str(ex)
                    break

    raise RuntimeError(
        f"All keys and models exhausted. Last: {last_error}\n"
        "Add more keys in Streamlit secrets as GEMINI_API_KEY_2 through _7."
    )


# ── Main agent class ──────────────────────────────────────────────────────────

class StudyBuddyAgent:

    ADMIN_PATTERNS = re.compile(
        r'(office hours|email:|@ntu\.edu\.sg|@e\.ntu|tutorial schedule|'
        r'lecture schedule|course outline|grading|assessment breakdown|'
        r'recommended textbook|course coordinator|guest lecture|'
        r'late submission|academic integrity|plagiarism|'
        r'course code|prerequisites|sc\d{4}|ce\d{4}|cz\d{4})',
        re.IGNORECASE
    )

    def __init__(self, api_key: str):
        self.api_key      = api_key
        self.store        = TFIDFVectorStore()
        self.doc_text     = ""
        self.total_chunks = 0

    def _is_admin_chunk(self, chunk: str) -> bool:
        hits = len(self.ADMIN_PATTERNS.findall(chunk))
        return hits >= 2 and len(chunk) < 700

    def ingest_pdf(self, uploaded_file) -> int:
        pdf_bytes = uploaded_file.read()
        doc       = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages     = []
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
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

    def retrieve(self, query, k=TOP_K):
        return "\n\n---\n\n".join(self.store.query(query, k=k))

    def retrieve_conceptual(self, k=8):
        queries = [
            "definition algorithm model method technique",
            "theory concept principle formula equation",
            "classification regression neural network learning",
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

    def summarise_by_slide(self) -> str:
        parts = re.split(r'(\[Page \d+\])', self.doc_text)
        pages = []
        i = 0
        while i < len(parts):
            if re.match(r'\[Page \d+\]', parts[i]) and i+1 < len(parts):
                num  = int(re.search(r'\d+', parts[i]).group())
                text = parts[i+1].strip()
                if text and not self._is_admin_chunk(text[:700]):
                    pages.append((num, text))
                i += 2
            else:
                i += 1
        if not pages:
            return "No content pages found after filtering admin slides."
        combined = "".join(f"[Page {n}]\n{t[:300]}\n\n" for n, t in pages[:20])
        system = "For each page, write ONE bullet: • **Page N:** [key concept]. One line per page only."
        result = call_gemini(self.api_key, system, combined, max_tokens=1500)
        if len(pages) > 20:
            result += f"\n\n*Showing first 20 of {len(pages)} pages.*"
        return result

    def answer_question(self, question: str) -> str:
        if any(p in question.lower() for p in
               ["slide by slide", "page by page", "each slide", "each page"]):
            return self.summarise_by_slide()

        page_req = re.search(r'(?:slide|page)s?\s*([\d]+)\s*(?:-|to)\s*([\d]+)', question.lower())
        if page_req:
            lo, hi = int(page_req.group(1)), int(page_req.group(2))
            available = sorted(set(int(p) for p in re.findall(r'\[Page (\d+)\]', self.doc_text)))
            if available and hi < available[0]:
                return (
                    f"**Pages {lo}–{hi} were filtered** (admin/cover content).\n\n"
                    f"First content page: **Page {available[0]}**\n\n"
                    f"Try asking about a topic instead."
                )

        ctx    = self.retrieve(question)
        system = """You are StudyBuddy AI, an expert study assistant.
RULES:
1. Answer ONLY from the provided lecture context. Never hallucinate.
2. Go straight to the answer — no greeting, no preamble.
3. Only greet if the message is ONLY "hi" or "hello" with nothing else.
4. For analogies: use context facts with real-world metaphors.
5. If not in the slides, say so honestly.

FORMAT: Direct answer → key concepts in **bold** → bullet points → 📖 Source: [page ref]"""
        try:
            return call_gemini(self.api_key, system,
                               f"Context:\n{ctx}\n\nQuestion: {question}",
                               max_tokens=1500)
        except RuntimeError as e:
            return f"❌ Error: {e}"

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
        system = """Generate exactly 5 MCQs from the content. ONLY test concepts/theory, never admin info.
FORMAT:
**Q1. [question]**
A) [option]
B) [option]
C) [option]
D) [option]
*(Answer: X — reason)*

All 5 questions. Never stop early."""
        try:
            for attempt in range(2):
                extra = "" if attempt == 0 else "\n\n[Attempt 2: output ALL 5 with A B C D each]"
                result = call_gemini(self.api_key, system,
                                     f"Generate all 5 from:\n\n{ctx}{extra}",
                                     max_tokens=2000)
                if self._validate_quiz(result):
                    return result
            if not self._validate_quiz(result):
                result += "\n\n⚠️ *Quiz may be incomplete. Click Generate again.*"
            return result
        except RuntimeError as e:
            return f"❌ Quiz failed: {e}"

    def check_answer(self, student_answer: str, context: str) -> str:
        system = """Check the quiz answer. State ✅ Correct! or ❌ Incorrect.
Give a full explanation (2-3 sentences): what the correct answer is and why.
End with: Topic: [2-3 word concept]. Max 4 sentences."""
        try:
            return call_gemini(self.api_key, system,
                               f"Question:\n{context}\n\nStudent: {student_answer}",
                               max_tokens=500)
        except RuntimeError as e:
            return f"❌ Error: {e}"

    def extract_topic(self, response: str):
        m = re.search(r'Topic:\s*\[?([\w\s\-]+)\]?', response, re.IGNORECASE)
        return m.group(1).strip() if m else "General Review"

    def _strip_admin_pages(self, text: str) -> str:
        admin_kw = ['office hours','email:','tutorial schedule','lecture schedule',
                    'course outline','grading','assessment','textbook',
                    'course coordinator','instructor','professor','guest lecture',
                    'attendance','plagiarism','academic integrity','late submission',
                    'course code','prerequisites','nanyang','ntu','semester']
        pages  = re.split(r'(\[Page \d+\])', text)
        result = []
        i = 0
        while i < len(pages):
            if re.match(r'\[Page \d+\]', pages[i]) and i+1 < len(pages):
                body = pages[i+1].lower()
                hits = sum(1 for kw in admin_kw if kw in body)
                if hits >= 3 and len(pages[i+1].strip()) < 800:
                    i += 2
                    continue
                result.append(pages[i] + pages[i+1])
                i += 2
            else:
                result.append(pages[i])
                i += 1
        return ''.join(result)

    def summarise(self) -> str:
        clean   = self._strip_admin_pages(self.doc_text)
        excerpt = clean[:6000]
        if len(clean) > 6000:
            excerpt += "\n\n[... document continues ...]"
        system = """Create exam-focused study notes. Technical content ONLY — ignore all admin.

## Key Topics
[3-6 bullets — technical subjects only]

## Core Concepts
[**Concept**: one-sentence definition]

## Quick Revision Points
[5-7 bullets — key exam facts]

## Likely Exam Questions
1. [question]
2. [question]
3. [question]

---
*Ask "summarise slide by slide" for page-by-page breakdown.*"""
        try:
            return call_gemini(self.api_key, system,
                               f"Summarise — technical only, ignore admin:\n\n{excerpt}",
                               max_tokens=1200)
        except RuntimeError as e:
            return f"❌ Summary failed: {e}"
