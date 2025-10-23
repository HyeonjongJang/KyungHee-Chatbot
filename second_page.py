# --- second_page.py (SPARQL 라우팅 + RAG 폴백) ---
import os
import re
import mimetypes
import ntpath
import unicodedata
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Tuple

import pandas as pd
import streamlit as st

# 파서/라우터 (있으면 Lark, 없으면 정규식 라우터)
try:
    from query_parser import parse_query
except Exception:
    from query_router import query_router as parse_query

from reranker import rerank

# LangChain 문서 타입 호환
try:
    from langchain.schema import Document as LC_Document
except Exception:
    try:
        from langchain_core.documents import Document as LC_Document
    except Exception:
        LC_Document = None

# 내부 체인 (FAISS RAG)
from chains import get_vector_store, get_retreiver_chain, get_conversational_rag
from langchain_core.messages import HumanMessage, AIMessage
from langsmith import Client
from langchain_core.tracers.context import collect_runs

# KG(Fuseki) 클라이언트 – 이번 수정의 핵심
from kg_client import (
    q_article15_details,
    q_article15_files_pages,
    q_article15_sameas,
    q_since_date,
    q_count_article_or_clause_none,
    q_undergrad_top5_for_cohort,
    require_rows,
    bindings_to_table,
    get_config,
)

client = Client()
APP_DIR = Path(__file__).resolve().parent

CATEGORIES = {
    "규정": "regulations",
    "학부 시행세칙": "undergrad_rules",
    "대학원 시행세칙": "grad_rules",
    "학사제도": "academic_system",
}

# ──────────────────────────────────────────────────────────────────────────────
# 파일 검색용(다운로드 버튼)
# ──────────────────────────────────────────────────────────────────────────────
SEARCH_ROOTS_DEFAULT = [
    APP_DIR / "past_documents",
    APP_DIR / "todo_documents",
    APP_DIR / "docs",
    APP_DIR / "backup",
    Path.cwd() / "past_documents",
    Path.cwd() / "todo_documents",
    Path.cwd() / "docs",
    Path.cwd() / "backup",
]
SEARCH_EXTS = {".pdf", ".PDF"}

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
        snippet = re.sub(rf"(?im)^\s*Source\s*:?\s*{re.escape(fname)}\s*", "", snippet)
    snippet = re.sub(r"(?im)^\s*Source\s*:\s*", "", snippet, count=1)
    return snippet.strip()

def _coerce_ctx_item(d) -> dict:
    """LangChain Document / dict / 문자열 → 화면 표준 스키마로 정규화"""
    item = {"filename": "", "page": "", "url": "", "snippet": ""}

    def _basename(s: str) -> str:
        if not s:
            return ""
        s = s.strip().strip('"').strip("'")
        s = s.split("?", 1)[0].split("#", 1)[0]
        s = s.split("/")[-1].split("\\")[-1]
        return s

    # dict
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

    # LC Document
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

    # Fallback 문자열
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

def _tokenize_name(s: str) -> List[str]:
    s = unicodedata.normalize("NFC", s or "")
    toks = re.findall(r"[0-9A-Za-z가-힣]+", s)
    return [t for t in (toks or []) if len(t) >= 2]

def _norm_key(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").casefold().strip()

def _norm_key_noext(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "").casefold().strip()
    s = re.sub(r"\.[a-z0-9]+$", "", s)
    s = re.sub(r"[\s_\-]+", "", s)
    s = re.sub(r"[(){}\[\]]", "", s)
    return s

@st.cache_resource(show_spinner=False)
def _build_source_index(extra_roots: Optional[List[Path]] = None) -> Dict[str, Dict]:
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
                    exact[_norm_key(name)] = str(p)
                    noext.setdefault(_norm_key_noext(name), []).append(str(p))
                    tokens[str(p)] = set(_tokenize_name(name))
        except Exception:
            continue

    return {"exact": exact, "noext": noext, "tokens": tokens}

def _find_source_file(filename: str) -> Optional[str]:
    if not filename:
        return None
    idx = _build_source_index()
    k = _norm_key(filename)
    if k in idx["exact"]:
        return idx["exact"][k]
    k2 = _norm_key_noext(filename)
    if k2 in idx["noext"]:
        cands = sorted(idx["noext"][k2], key=lambda x: len(x))
        return cands[0] if cands else None
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

def _overlap_score(a: str, b: str) -> float:
    ta = {t for t in re.findall(r"\w+", (a or "").lower()) if len(t) >= 2}
    tb = {t for t in re.findall(r"\w+", (b or "").lower()) if len(t) >= 2}
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / (len(tb) or 1)

def _strip_llm_source_lines(text: str) -> str:
    return re.sub(r"(?im)^\s*source\s*:\s*.*$", "", text).strip()

# ──────────────────────────────────────────────────────────────────────────────
# SPARQL 라우팅 (여기서 매칭되면 FAISS RAG를 건너뜀)
# ──────────────────────────────────────────────────────────────────────────────
def _route_sparql(user_input: str) -> Optional[Tuple[str, List[List[str]], List[str]]]:
    """
    매칭되면 (섹션타이틀, 표데이터, 컬럼명) 반환, 아니면 None
    """
    q = user_input.strip()

    # 1) 제15조 … 설명
    if re.search(r"제?15\s*조.*설명", q):
        rows = q_article15_details(category="regulations")
        require_rows(rows, "제15조 관련 데이터가 없습니다.")
        cols = ["s", "article", "clause", "label", "src", "page", "effFrom"]
        table = bindings_to_table(rows, cols)
        return ("제15조 상세", table, cols)

    # 2) 2025학번 기준 … 2025-04-30 이후 효력 … regulations
    if re.search(r"2025\s*학번.*2025-04-30.*(이후|이상).*효력.*regulations", q, flags=re.I):
        rows = q_since_date("regulations", "2025", "2025-04-30")
        require_rows(rows, "해당 조건에 맞는 데이터가 없습니다.")
        cols = ["s", "article", "clause", "effFrom", "src", "page"]
        table = bindings_to_table(rows, cols)
        return ("2025학번 기준 2025-04-30 이후 효력 조항", table, cols)

    # 3) 제15조로 표기된 … 파일/페이지
    if re.search(r"제?15\s*조.*(파일|페이지)", q):
        rows = q_article15_files_pages("regulations")
        require_rows(rows, "제15조의 파일/페이지 정보가 없습니다.")
        cols = ["src", "page"]
        table = bindings_to_table(rows, cols)
        return ("제15조 파일/페이지", table, cols)

    # 4) 제15조 URN … 매핑된 Clause
    if re.search(r"제?15\s*조.*URN.*매핑.*Clause", q, flags=re.I):
        rows = q_article15_sameas("regulations")
        require_rows(rows, "제15조 URN 매핑 정보가 없습니다.")
        cols = ["s", "urn"]
        table = bindings_to_table(rows, cols)
        return ("제15조 URN sameAs", table, cols)

    # 5) article 또는 clause 값이 None
    if re.search(r"article\s*또는\s*clause.*None.*(개수|수)", q, flags=re.I):
        rows = q_count_article_or_clause_none("regulations")
        require_rows(rows, "카운트 결과가 없습니다.")
        cols = ["n"]
        table = bindings_to_table(rows, cols)
        return ("article/clause None 개수", table, cols)

    # 6) 학부(UG) + 2025학번 … 5개
    if re.search(r"(학부|UG).*(2025).*5\s*개", q, flags=re.I):
        rows = q_undergrad_top5_for_cohort("2025")
        require_rows(rows, "UG 2025 결과가 없습니다.")
        cols = ["s", "article", "clause", "effFrom", "src"]
        table = bindings_to_table(rows, cols)
        return ("학부 2025 TOP5", table, cols)

    return None

# ──────────────────────────────────────────────────────────────────────────────
# Cohort 헬퍼
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# 메인 UI
# ──────────────────────────────────────────────────────────────────────────────
def second_page():
    st.header("Kyung Hee University's Regulations Chatbot")

    # 파일 인덱스 캐시 준비
    _build_source_index()

    # 카테고리 선택
    st.subheader("검색 범주 선택")
    labels = list(CATEGORIES.keys())
    default_idx = 0
    sel_label = st.radio(
        "다음 중 하나를 선택하세요:",
        labels,
        index=st.session_state.get("kb_category_idx", default_idx),
        horizontal=True,
    )
    sel_slug = CATEGORIES[sel_label]
    st.session_state["kb_category_idx"] = labels.index(sel_label)
    st.session_state.setdefault("kb_category_slug", sel_slug)
    changed_category = (st.session_state["kb_category_slug"] != sel_slug)
    st.session_state["kb_category_slug"] = sel_slug

    # 코호트 선택(학부/대학원 시행세칙)
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
            for k in ["student_id", "chat_histories", "vector_stores", "dialog_identifier", "kb_cohort"]:
                st.session_state.pop(k, None)
            st.rerun()
    with col2:
        if st.button("Refresh", key="refresh"):
            if "chat_histories" in st.session_state:
                st.session_state["chat_histories"][vs_key] = []
            st.session_state.pop("dialog_identifier", None)
            st.rerun()

    # 세션 상태
    st.session_state.setdefault("dialog_identifier", uuid.uuid4())
    st.session_state.setdefault("vector_stores", {})
    st.session_state.setdefault("chat_histories", {})
    st.session_state["chat_histories"].setdefault(vs_key, [])

    # 벡터스토어 준비 (RAG 폴백용)
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

    # 사용자 입력
    if user_input := st.chat_input("질문을 입력하세요 (예: '제15조 URN과 매핑된 Clause 보여줘')"):
        st.chat_message("Human").write(user_input)

        # 0) 먼저 SPARQL 라우팅 시도
        try:
            routed = _route_sparql(user_input)
        except Exception as e:
            routed = None
            st.warning(f"SPARQL 라우팅 오류: {e}")

        if routed:
            section, table, cols = routed
            # 결과가 비어 있으면 실패 처리
            if not table:
                ai_text = "해당 조건의 결과가 없습니다."
                st.chat_message("AI").write(ai_text)
                st.session_state["chat_histories"][vs_key].append(HumanMessage(content=user_input))
                st.session_state["chat_histories"][vs_key].append(AIMessage(content=ai_text))
            else:
                st.chat_message("AI").markdown(f"**{section}** — 총 {len(table)}건")
                df = pd.DataFrame(table, columns=cols)
                st.dataframe(df, use_container_width=True)
                # 채팅 히스토리 저장(간단 요약)
                ai_text = f"{section} — {len(table)}건"
                st.session_state["chat_histories"][vs_key].append(HumanMessage(content=user_input))
                st.session_state["chat_histories"][vs_key].append(AIMessage(content=ai_text))
            return  # SPARQL 경로면 여기서 종료

        # 1) SPARQL 매칭이 아니면 RAG로 폴백
        with collect_runs() as cb:
            with st.spinner("Searching..."):
                meta_filter, hints = parse_query(user_input)
                top_k = 7 if hints.get("wants_table") else 5
                history_retriever_chain = get_retreiver_chain(vs, meta_filter=meta_filter, top_k=top_k)
                conversation_rag_chain = get_conversational_rag(history_retriever_chain)
                response = conversation_rag_chain.invoke(
                    {
                        "chat_history": st.session_state["chat_histories"][vs_key],
                        "input": user_input,
                        "student_id": st.session_state.get("student_id"),
                        "dialog_identifier": st.session_state["dialog_identifier"],
                    }
                )

                raw_answer = response.get("answer", "") or ""
                contexts = response.get("context", []) or []

                # 컨텍스트 없으면 데이터-기반 응답 금지
                if not contexts:
                    ai_text = "해당 조건의 결과가 없습니다."
                    st.chat_message("AI").write(ai_text)
                    st.session_state["chat_histories"][vs_key].append(HumanMessage(content=user_input))
                    st.session_state["chat_histories"][vs_key].append(AIMessage(content=ai_text))
                    return

                # 리랭킹
                try:
                    contexts = rerank(contexts or [], hints, user_input)
                except Exception:
                    pass

                answer = _strip_llm_source_lines(raw_answer)

                # 상위 컨텍스트 선별
                TOPK_CONTEXTS = 5
                MIN_OVERLAP = 0.12
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
                coerced = sorted(by_file.values(), key=lambda x: x["_score"], reverse=True)[:TOPK_CONTEXTS]

                # Source 라인
                source_files = [c["filename"] for c in coerced if c.get("filename")]
                if source_files:
                    answer = f"{answer}\n\nSource: " + ", ".join(source_files)

                st.chat_message("AI").write(answer)

                # 미리보기(다운로드 포함)
                if coerced:
                    with st.expander("📑 참고한 문서 조각 (미리보기)"):
                        for i, c in enumerate(coerced, 1):
                            header = c["filename"] or "문서"
                            if c["page"]:
                                header += f" (p.{c['page']})"
                            st.markdown(f"**{i}. {header}**")
                            st.markdown(f"> {c['snippet']}")
                            bcol1, bcol2 = st.columns([1, 1], vertical_alignment="center")
                            with bcol1:
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
                                    st.caption(" ")

                # 히스토리 저장
                st.session_state["chat_histories"][vs_key].append(HumanMessage(content=user_input))
                st.session_state["chat_histories"][vs_key].append(AIMessage(content=answer))

            st.session_state.run_id = cb.traced_runs[0].id if cb.traced_runs else None

    # (선택) 피드백 위젯 등은 필요 시 유지/삭제
