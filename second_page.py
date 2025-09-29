# --- second_page.py (drop-in; cohort-aware, reliable Source display, robust file finder) ---
import os
import re
import mimetypes
import ntpath
import unicodedata
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Tuple

try:
    from langchain.schema import Document as LC_Document
except Exception:
    try:
        from langchain_core.documents import Document as LC_Document
    except Exception:
        LC_Document = None

try:
    from ragas import evaluate as ragas_evaluate
    from ragas.metrics import faithfulness as ragas_faithfulness, answer_relevancy as ragas_answer_rel
    from datasets import Dataset as HF_Dataset
    _HAS_RAGAS = True
except Exception:
    _HAS_RAGAS = False

import streamlit as st
from chains import get_vector_store, get_retreiver_chain, get_conversational_rag
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tracers.context import collect_runs
from langsmith import Client
from streamlit_feedback import streamlit_feedback

client = Client()
APP_DIR = Path(__file__).resolve().parent

CATEGORIES = {
    "규정": "regulations",
    "학부 시행세칙": "undergrad_rules",
    "대학원 시행세칙": "grad_rules",
    "학사제도": "academic_system",
}

# ──────────────────────────────────────────────────────────────────────────────
# File search settings
# ──────────────────────────────────────────────────────────────────────────────
# 원문 PDF를 찾기 위해 스캔할 루트들(필요시 여기에 경로 추가)
SEARCH_ROOTS_DEFAULT = [
    APP_DIR / "past_documents",
    APP_DIR / "todo_documents",
    APP_DIR / "docs",                   # ← docs 아래 originals/연도/카테고리 등 모두 커버
    APP_DIR / "backup",
    Path.cwd() / "past_documents",
    Path.cwd() / "todo_documents",
    Path.cwd() / "docs",
    Path.cwd() / "backup",
]

SEARCH_EXTS = {".pdf", ".PDF"}  # 필요시 .docx 등 추가

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False, ttl=600)
def _compute_ragas_scores(question: str, answer: str, contexts_snippets: list[str]) -> dict:
    if not _HAS_RAGAS:
        try:
            approx = _overlap_score(answer, " ".join(contexts_snippets))
        except Exception:
            approx = 0.0
        return {"faithfulness": None, "answer_relevancy": approx}
    samples = [{"question": question or "",
                "answer": answer or "",
                "contexts": [s or "" for s in contexts_snippets] or [""]}]
    ds = HF_Dataset.from_list(samples)
    res = ragas_evaluate(ds, metrics=[ragas_faithfulness, ragas_answer_rel])
    try:
        f = float(res["faithfulness"][0])
    except Exception:
        f = None
    try:
        a = float(res["answer_relevancy"][0])
    except Exception:
        a = None
    return {"faithfulness": f, "answer_relevancy": a}

def _basename_crossplat(p: str) -> str:
    if not p:
        return ""
    p = p.strip().strip('"').strip("'")
    name = ntpath.basename(p)
    name = name.split("/")[-1].split("\\")[-1]
    return unicodedata.normalize("NFC", name)

def _strip_source_prefix(snippet: str, fname: str) -> str:
    if not snippet:
        return ""
    if fname:
        snippet = re.sub(
            rf"(?im)^\s*Source\s*:?\s*{re.escape(fname)}\s*",
            "",
            snippet
        )
    snippet = re.sub(r"(?im)^\s*Source\s*:\s*", "", snippet, count=1)
    return snippet.strip()

def _coerce_ctx_item(d) -> dict:
    """
    LangChain Document / dict / 문자열 표현까지 모두 받아
    화면 표시용 표준 스키마로 정규화.
    return: {"filename": str, "page": str, "url": str, "snippet": str}
    """
    item = {"filename": "", "page": "", "url": "", "snippet": ""}

    def _basename(s: str) -> str:
        if not s:
            return ""
        s = s.strip().strip('"').strip("'")
        s = s.split("?", 1)[0].split("#", 1)[0]
        s = s.split("/")[-1].split("\\")[-1]
        return s

    # 1) dict 형태
    if isinstance(d, dict):
        meta = d.get("metadata") or {}
        text = (d.get("page_content") or d.get("content") or "") or ""
        fname = meta.get("filename") or _basename(meta.get("source", ""))
        page  = meta.get("page") or meta.get("page_number") or meta.get("pageIndex") or ""
        url   = meta.get("url") or meta.get("source_url") or meta.get("document_url") or ""
        if not fname and text:
            first = text.splitlines()[0].strip()
            if first.lower().startswith("source"):
                maybe = first.split(":", 1)[-1].strip()
                fname = _basename(maybe)
        text = _strip_source_prefix(text, fname)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 280:
            text = text[:279] + "…"
        item.update({"filename": fname or "", "page": str(page) if page is not None else "", "url": url or "", "snippet": text})
        return item

    # 2) LangChain Document 객체
    if LC_Document is not None and isinstance(d, LC_Document):
        meta = getattr(d, "metadata", {}) or {}
        text = getattr(d, "page_content", "") or ""
        fname = meta.get("filename") or _basename(meta.get("source", ""))
        page  = meta.get("page") or meta.get("page_number") or meta.get("pageIndex") or ""
        url   = meta.get("url") or meta.get("source_url") or meta.get("document_url") or ""
        if not fname and text:
            first = text.splitlines()[0].strip()
            if first.lower().startswith("source"):
                maybe = first.split(":", 1)[-1].strip()
                fname = _basename(maybe)
        text = _strip_source_prefix(text, fname)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 280:
            text = text[:279] + "…"
        item.update({"filename": fname or "", "page": str(page) if page is not None else "", "url": url or "", "snippet": text})
        return item

    # 3) 문자열 표현
    s = str(d or "")
    m = re.search(r"page_content\s*=\s*['\"](.*?)['\"]\s*,", s, flags=re.S)
    text = m.group(1) if m else s
    fname = ""
    first = text.splitlines()[0].strip() if text else ""
    if first.lower().startswith("source"):
        maybe = first.split(":", 1)[-1].strip()
        fname = _basename(maybe)
    mpage = re.search(r"[{,]\s*['\"]?(page|page_number|pageIndex)['\"]?\s*:\s*['\"]?(\d+)['\"]?", s)
    page = mpage.group(2) if mpage else ""
    text = _strip_source_prefix(text, fname)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 280:
        text = text[:279] + "…"
    item.update({"filename": fname or "", "page": str(page) if page is not None else "", "url": "", "snippet": text})
    return item

def _overlap_score(a: str, b: str) -> float:
    ta = {t for t in re.findall(r"\w+", (a or "").lower()) if len(t) >= 2}
    tb = {t for t in re.findall(r"\w+", (b or "").lower()) if len(t) >= 2}
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / (len(tb) or 1)

# ──────────────────────────────────────────────────────────────────────────────
# Robust file finder (indexed & fuzzy)
# ──────────────────────────────────────────────────────────────────────────────

def _norm_key(s: str) -> str:
    """확장자 포함한 기본 키(정확 일치용)"""
    return unicodedata.normalize("NFC", s or "").casefold().strip()

def _norm_key_noext(s: str) -> str:
    """확장자 제거 + 단순화 키(퍼지 후보용)"""
    s = unicodedata.normalize("NFC", s or "").casefold().strip()
    s = re.sub(r"\.[a-z0-9]+$", "", s)                  # remove extension
    s = re.sub(r"[\s_\-]+", "", s)                      # remove spaces/_/-
    s = re.sub(r"[(){}\[\]]", "", s)                    # remove brackets
    return s

def _tokenize_name(s: str) -> List[str]:
    """한글/영문/숫자 토큰화 (길이>=2만 남김)"""
    s = unicodedata.normalize("NFC", s or "")
    toks = re.findall(r"[0-9A-Za-z가-힣]+", s)
    return [t for t in (toks or []) if len(t) >= 2]

@st.cache_resource(show_spinner=False)
def _build_source_index(extra_roots: Optional[List[Path]] = None) -> Dict[str, Dict]:
    """
    전체 PDF 파일을 스캔해 인덱스를 구성.
    반환:
      {
        "exact": { norm_fullname : path_str, ... },
        "noext": { norm_noext : [path_str, ...] },
        "tokens": { path_str : set(tokens) }
      }
    """
    roots: List[Path] = []
    seen = set()
    for r in (SEARCH_ROOTS_DEFAULT + (extra_roots or [])):
        try:
            rp = r.resolve()
            if rp.exists() and rp.is_dir() and str(rp) not in seen:
                roots.append(rp)
                seen.add(str(rp))
        except Exception:
            continue

    exact: Dict[str, str] = {}
    noext: Dict[str, List[str]] = {}
    tokens: Dict[str, set] = {}

    for root in roots:
        try:
            for p in root.rglob("*"):
                if p.is_file() and p.suffix in SEARCH_EXTS:
                    name = p.name
                    k_exact = _norm_key(name)
                    exact[k_exact] = str(p)
                    k_noext = _norm_key_noext(name)
                    noext.setdefault(k_noext, []).append(str(p))
                    tokens[str(p)] = set(_tokenize_name(name))
        except Exception:
            continue

    return {"exact": exact, "noext": noext, "tokens": tokens}

def _find_source_file(filename: str) -> Optional[str]:
    """
    1) 정확 일치(NFC/casefold)
    2) 확장자/공백/_/- 제거 일치
    3) 토큰 겹침 최대 후보(퍼지)
    """
    if not filename:
        return None
    idx = _build_source_index()

    # 1) exact
    k = _norm_key(filename)
    if k in idx["exact"]:
        return idx["exact"][k]

    # 2) noext (확장자, 공백/언더스코어/대시 무시)
    k2 = _norm_key_noext(filename)
    if k2 in idx["noext"]:
        # 여러 개면 가장 짧은 경로(가까운 폴더)를 우선
        cands = sorted(idx["noext"][k2], key=lambda x: len(x))
        return cands[0] if cands else None

    # 3) fuzzy by token overlap
    want = set(_tokenize_name(filename))
    best_path, best_score = None, 0
    if want:
        for path, toks in idx["tokens"].items():
            if not toks:
                continue
            score = len(want & toks)
            if score > best_score:
                best_score, best_path = score, path
    return best_path

# ──────────────────────────────────────────────────────────────────────────────
# UI: context previews with download buttons
# ──────────────────────────────────────────────────────────────────────────────

def _render_context_previews(contexts: list, max_items: int = 5):
    if not contexts:
        return
    with st.expander("📑 참고한 문서 조각 (미리보기)"):
        for i, d in enumerate(contexts[:max_items], 1):
            c = d if (isinstance(d, dict) and ("filename" in d and "snippet" in d)) else _coerce_ctx_item(d)
            header = c["filename"] or "문서"
            if c["page"]:
                header += f" (p.{c['page']})"
            st.markdown(f"**{i}. {header}**")
            st.markdown(f"> {c['snippet']}")

            bcol1, bcol2 = st.columns([1, 1], vertical_alignment="center")
            with bcol1:
                if c["url"]:
                    st.link_button("원문 열기", c["url"], use_container_width=True)
                else:
                    st.caption(" ")

            with bcol2:
                fname = c["filename"]
                if fname:
                    found_path = _find_source_file(fname)
                    if found_path and os.path.exists(found_path):
                        mime, _ = mimetypes.guess_type(fname)
                        dl_key = f"ctxdl_{st.session_state.get('dialog_identifier','')}_{i}_{fname}"
                        with open(found_path, "rb") as f:
                            st.download_button(
                                label=f"📥 {fname}",
                                data=f,
                                file_name=fname,
                                mime=mime or "application/pdf",
                                key=dl_key,
                                use_container_width=True,
                            )
                    else:
                        st.caption("⚠️ 로컬에서 파일을 찾을 수 없습니다.")
                else:
                    st.caption("⚠️ 파일명이 없어 다운로드를 제공할 수 없습니다.")
            st.divider()

def _extract_source_filenames(contexts) -> List[str]:
    def _basename(p: str) -> str:
        if not p:
            return ""
        p = p.strip().strip('"').strip("'")
        name = ntpath.basename(p)
        name = name.split("/")[-1].split("\\")[-1]
        return unicodedata.normalize("NFC", name)

    seen, out = set(), []
    for d in contexts or []:
        name = ""
        if isinstance(d, dict):
            meta = d.get("metadata") or {}
            name = meta.get("filename") or _basename(meta.get("source", ""))
            if (not name) and (d.get("page_content") or d.get("content")):
                first = (d.get("page_content") or d.get("content") or "").splitlines()[0].strip()
                if first.lower().startswith("source"):
                    maybe = first.split(":", 1)[-1].strip()
                    name = _basename(maybe)
        else:
            if LC_Document is not None and isinstance(d, LC_Document):
                meta = getattr(d, "metadata", {}) or {}
                name = meta.get("filename") or _basename(meta.get("source", ""))
                if (not name) and getattr(d, "page_content", ""):
                    first = d.page_content.splitlines()[0].strip()
                    if first.lower().startswith("source"):
                        maybe = first.split(":", 1)[-1].strip()
                        name = _basename(maybe)
            else:
                s = str(d or "")
                m = re.search(r"page_content\s*=\s*['\"](.*?)['\"]\s*,", s, flags=re.S)
                text = m.group(1) if m else s
                first = text.splitlines()[0].strip() if text else ""
                if first.lower().startswith("source"):
                    maybe = first.split(":", 1)[-1].strip()
                    name = _basename(maybe)
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out

def _list_available_cohorts(slug: str) -> List[str]:
    base = APP_DIR / "faiss_db" / slug
    out = []
    if base.exists():
        for p in base.iterdir():
            if p.is_dir() and (p / "index.faiss").exists():
                out.append(p.name)
    try:
        out.sort(key=lambda x: int(x), reverse=True)
    except Exception:
        out.sort(reverse=True)
    return out

def _infer_default_cohort(student_id: Optional[str], cohorts: List[str]) -> int:
    if not cohorts:
        return 0
    if not student_id:
        return 0
    digits = "".join(ch for ch in str(student_id) if ch.isdigit())
    candidates = []
    if len(digits) >= 4:
        candidates.append(digits[:4])
    if len(digits) >= 2:
        yy = int(digits[:2])
        if 0 <= yy <= 99:
            candidates.append(f"20{yy:02d}")
    for c in candidates:
        if c in cohorts:
            return cohorts.index(c)
    return 0

def _strip_llm_source_lines(text: str) -> str:
    return re.sub(r"(?im)^\s*source\s*:\s*.*$", "", text).strip()

# ──────────────────────────────────────────────────────────────────────────────
# Main Page
# ──────────────────────────────────────────────────────────────────────────────

def second_page():
    st.header("Kyung Hee University's Regulations Chatbot")

    # 한 번만 구축되는 파일 인덱스(캐시) 미리 준비
    _build_source_index()

    # --- 카테고리 선택 UI ---
    st.subheader("검색 범주 선택")
    labels = list(CATEGORIES.keys())
    default_idx = 0
    sel_label = st.radio(
        "다음 중 하나를 선택하세요:",
        labels,
        index=st.session_state.get("kb_category_idx", default_idx),
        horizontal=True
    )
    sel_slug = CATEGORIES[sel_label]
    st.session_state["kb_category_idx"] = labels.index(sel_label)
    st.session_state.setdefault("kb_category_slug", sel_slug)
    changed_category = (st.session_state["kb_category_slug"] != sel_slug)
    st.session_state["kb_category_slug"] = sel_slug

    # --- 코호트 선택(학부/대학원 시행세칙만) ---
    st.session_state.setdefault("kb_cohort", {})
    cohort = None
    cohort_changed = False
    if sel_slug in ("undergrad_rules", "grad_rules"):
        cohorts = _list_available_cohorts(sel_slug)
        if not cohorts:
            st.error(
                "해당 범주에서 사용 가능한 입학년도 인덱스가 없습니다.\n"
                f"예: todo_documents/{sel_slug}/2020/ 에 문서를 넣고 "
                f"`python add_document.py --category {sel_slug} --cohort 2020` 실행 후 이용하세요."
            )
            return
        prev = st.session_state["kb_cohort"].get(sel_slug)
        default_idx = (
            _infer_default_cohort(st.session_state.get("student_id"), cohorts)
            if prev is None else (cohorts.index(prev) if prev in cohorts else 0)
        )
        sel_cohort = st.selectbox("입학년도(학번) 선택", cohorts, index=default_idx, key=f"cohort_{sel_slug}")
        cohort = sel_cohort
        cohort_changed = (prev != cohort)
        st.session_state["kb_cohort"][sel_slug] = cohort

    vs_key = f"{sel_slug}:{cohort or 'all'}"

    # 상단 버튼
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Go to Home", key="home_page"):
            st.session_state.pop("student_id", None)
            st.session_state.pop("chat_histories", None)
            st.session_state.pop("vector_stores", None)
            st.session_state.pop("dialog_identifier", None)
            st.session_state.pop("kb_cohort", None)
            st.rerun()
    with col2:
        if st.button("Refresh", key="refresh"):
            if "chat_histories" in st.session_state:
                st.session_state["chat_histories"][vs_key] = []
            st.session_state.pop("dialog_identifier", None)
            st.rerun()

    # 세션 상태 초기화
    st.session_state.setdefault("dialog_identifier", uuid.uuid4())
    st.session_state.setdefault("vector_stores", {})
    st.session_state.setdefault("chat_histories", {})
    st.session_state["chat_histories"].setdefault(vs_key, [])

    # 벡터스토어 준비
    vs = st.session_state["vector_stores"].get(vs_key)
    if (vs is None) or changed_category or cohort_changed:
        try:
            vs = get_vector_store(sel_slug, cohort=cohort)
            st.session_state["vector_stores"][vs_key] = vs
        except FileNotFoundError:
            if sel_slug in ("undergrad_rules", "grad_rules"):
                st.error(
                    f"선택한 범주/연도('{sel_label} / {cohort}')에 대한 벡터 DB가 없습니다.\n"
                    f"todo_documents/{sel_slug}/{cohort}/ 에 문서를 넣고\n"
                    f"`python add_document.py --category {sel_slug} --cohort {cohort}`로 인덱스를 구축해 주세요."
                )
            else:
                st.error(f"선택한 범주('{sel_label}')에 대한 벡터 DB가 없습니다. 먼저 add_document.py로 구축해 주세요.")
            return

    # 이전 대화 렌더링
    for message in st.session_state["chat_histories"][vs_key]:
        role = "AI" if isinstance(message, AIMessage) else "Human"
        with st.chat_message("AI" if role == "AI" else "Human"):
            st.write(message.content)

    # 응답 생성 함수
    def get_response(user_input):
        history_retriever_chain = get_retreiver_chain(vs)
        conversation_rag_chain = get_conversational_rag(history_retriever_chain)
        response = conversation_rag_chain.invoke(
            {
                "chat_history": st.session_state["chat_histories"][vs_key],
                "input": user_input,
                "student_id": st.session_state.get("student_id"),
                "dialog_identifier": st.session_state["dialog_identifier"],
            }
        )
        answer = response["answer"]
        contexts = response.get("context", [])
        return answer, contexts

    # 사용자 입력
    if user_input := st.chat_input("Type your message here..."):
        st.chat_message("Human").write(user_input)

        with collect_runs() as cb:
            with st.spinner("Thinking..."):
                raw_answer, contexts = get_response(user_input)
                answer = _strip_llm_source_lines(raw_answer)

                # 상위 컨텍스트 선별
                TOPK_CONTEXTS  = st.session_state.get("topk_ctx", 5) if "topk_ctx" in st.session_state else 5
                MIN_OVERLAP    = 0.12
                MAX_SOURCES    = TOPK_CONTEXTS

                normalized = [_coerce_ctx_item(d) for d in (contexts or [])]
                scored = []
                for c in normalized:
                    fname = (c.get("filename") or "").strip()
                    score = _overlap_score(answer, c.get("snippet", ""))
                    scored.append({**c, "_score": score, "_has_name": bool(fname)})
                filtered = [c for c in scored if c["_score"] >= MIN_OVERLAP]
                by_file = {}
                for c in filtered:
                    fname = (c.get("filename") or "").strip()
                    if not fname:
                        continue
                    best = by_file.get(fname)
                    if (best is None) or (c["_score"] > best["_score"]):
                        by_file[fname] = c
                top_by_file = sorted(by_file.values(), key=lambda x: x["_score"], reverse=True)[:MAX_SOURCES]
                coerced = top_by_file

                # Source 라인
                source_files = [c["filename"] for c in coerced if c.get("filename")]
                if source_files:
                    answer = f"{answer}\n\nSource: " + ", ".join(source_files)

                # RAGAS (옵션)
                ragas_snippets = [c.get("snippet", "") for c in coerced][:5]
                scores = _compute_ragas_scores(user_input, answer, ragas_snippets)

                # 출력
                st.chat_message("AI").write(answer)

                with st.container(border=True):
                    st.markdown("#### 🧪 응답 품질 점수 (RAGAS)")
                    colA, colB = st.columns(2)
                    f = scores.get("faithfulness")
                    r = scores.get("answer_relevancy")
                    def _pct(x): return f"{x*100:.1f}%" if isinstance(x, (int, float)) else "N/A"
                    colA.metric("충실도 (근거 대비 일치도)", _pct(f))
                    colB.metric("답변_관련성 (질문 대비 적합도)", _pct(r))

                _render_context_previews(coerced, max_items=len(coerced) if coerced else 0)

                # 히스토리 저장
                st.session_state["chat_histories"][vs_key].append(HumanMessage(content=user_input))
                st.session_state["chat_histories"][vs_key].append(AIMessage(content=answer))

            st.session_state.run_id = cb.traced_runs[0].id if cb.traced_runs else None

    # 피드백
    feedback_option = "thumbs"
    if st.session_state.get("run_id"):
        run_id = st.session_state.run_id
        feedback = streamlit_feedback(
            feedback_type="thumbs",
            optional_text_label="[Optional] Please provide an explanation",
            key=f"feedback_{run_id}",
        )
        score_mappings = {"thumbs": {"👍": 1, "👎": -1},
                          "faces": {"😀": 1, "🙂": 0.75, "😐": 0.5, "🙁": 0.25, "😞": 0}}
        if feedback:
            score = score_mappings[feedback_option].get(feedback["score"])
            if score is not None:
                feedback_type_str = f"{feedback_option} {feedback['score']}"
                feedback_record = client.create_feedback(
                    run_id, feedback_type_str, score=score, comment=feedback.get("text"),
                )
                st.session_state.feedback = {"feedback_id": str(feedback_record.id), "score": score}
            else:
                st.warning("Invalid feedback score.")
