# --- second_page.py (drop-in; cohort-aware & reliable Source display) ---
import os
import re
try:
    from langchain.schema import Document as LC_Document
except Exception:
    try:
        from langchain_core.documents import Document as LC_Document
    except Exception:
        LC_Document = None
import mimetypes
import ntpath
import unicodedata
import uuid
from pathlib import Path
from typing import Optional, List

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
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _basename_crossplat(p: str) -> str:
    if not p:
        return ""
    p = p.strip().strip('"').strip("'")
    name = ntpath.basename(p)
    name = name.split("/")[-1].split("\\")[-1]
    return unicodedata.normalize("NFC", name)

def _coerce_ctx_item(d) -> dict:
    """
    LangChain Document / dict / 문자열 표현까지 모두 받아
    화면 표시용 표준 스키마로 정규화.
    return: {"filename": str, "page": str, "url": str, "snippet": str}
    """
    item = {"filename": "", "page": "", "url": "", "snippet": ""}

    # 0) 공통 유틸
    def _basename(s: str) -> str:
        if not s:
            return ""
        s = s.strip().strip('"').strip("'")
        s = s.split("?", 1)[0].split("#", 1)[0]
        s = s.split("/")[-1].split("\\")[-1]
        return s

    def _strip_source_prefix(snippet: str, fname: str) -> str:
        # "Source : 파일명" / "Source: 파일명" 접두사 제거(첫 줄 위주)
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

    # 1) dict 형태
    if isinstance(d, dict):
        meta = d.get("metadata") or {}
        text = (d.get("page_content") or d.get("content") or "") or ""
        fname = meta.get("filename") or _basename(meta.get("source", ""))
        page  = meta.get("page") or meta.get("page_number") or meta.get("pageIndex") or ""
        url   = meta.get("url") or meta.get("source_url") or meta.get("document_url") or ""

        # page_content 첫 줄에서 filename 백업 추출
        if not fname and text:
            first = text.splitlines()[0].strip()
            if first.lower().startswith("source"):
                maybe = first.split(":", 1)[-1].strip()
                fname = _basename(maybe)

        # 스니펫 정리
        text = _strip_source_prefix(text, fname)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 280:
            text = text[:279] + "…"

        item.update({
            "filename": fname or "",
            "page": str(page) if page is not None else "",
            "url": url or "",
            "snippet": text
        })
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

        item.update({
            "filename": fname or "",
            "page": str(page) if page is not None else "",
            "url": url or "",
            "snippet": text
        })
        return item

    # 3) 문자열 표현 (예: "Document(page_content='...', metadata={...})")
    s = str(d or "")
    # page_content='...'(또는 "page_content=\"...\"") 구간을 파싱
    m = re.search(r"page_content\s*=\s*['\"](.*?)['\"]\s*,", s, flags=re.S)
    text = m.group(1) if m else s

    # filename 후보: "Source : 파일명" 첫 줄에서 추출
    fname = ""
    first = text.splitlines()[0].strip() if text else ""
    if first.lower().startswith("source"):
        maybe = first.split(":", 1)[-1].strip()
        fname = _basename(maybe)

    # page 후보: metadata={'page': N} 등 문자열에서 파싱 시도
    mpage = re.search(r"[{,]\s*['\"]?(page|page_number|pageIndex)['\"]?\s*:\s*['\"]?(\d+)['\"]?", s)
    page = mpage.group(2) if mpage else ""

    # 정리
    text = _strip_source_prefix(text, fname)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 280:
        text = text[:279] + "…"

    item.update({
        "filename": fname or "",
        "page": str(page) if page is not None else "",
        "url": "",
        "snippet": text
    })
    return item

def _overlap_score(a: str, b: str) -> float:
    """
    답변(a)과 스니펫(b)의 토큰 교집합 비율을 간단히 계산.
    길이 2 이상 토큰만 사용.
    """
    ta = {t for t in re.findall(r"\w+", (a or "").lower()) if len(t) >= 2}
    tb = {t for t in re.findall(r"\w+", (b or "").lower()) if len(t) >= 2}
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / (len(tb) or 1)

def _render_context_previews(contexts: list, max_items: int = 5):
    """
    컨텍스트 문서 조각을 예쁘게 렌더링합니다.
    - 파일명, 페이지, 스니펫
    - (있다면) URL 열기 버튼
    - ⚡ 미리보기 카드마다 해당 파일 '개별 다운로드' 버튼 추가
    """
    if not contexts:
        return
    with st.expander("📑 참고한 문서 조각 (미리보기)"):
        for i, d in enumerate(contexts[:max_items], 1):
            c = _coerce_ctx_item(d)
            header = c["filename"] or "문서"
            if c["page"]:
                header += f" (p.{c['page']})"

            st.markdown(f"**{i}. {header}**")
            st.markdown(f"> {c['snippet']}")

            # 버튼 영역: URL 열기 / 개별 다운로드
            bcol1, bcol2 = st.columns([1, 1], vertical_alignment="center")

            with bcol1:
                if c["url"]:
                    st.link_button("원문 열기", c["url"], use_container_width=True)
                else:
                    st.caption(" ")  # 자리 맞춤

            with bcol2:
                fname = c["filename"]
                if fname:
                    found_path = _find_source_file(fname)
                    if found_path and os.path.exists(found_path):
                        mime, _ = mimetypes.guess_type(fname)
                        # 각 카드마다 고유 key 필요: dialog_identifier + index + filename
                        dl_key = f"ctxdl_{st.session_state.get('dialog_identifier','')}_{i}_{fname}"
                        with open(found_path, "rb") as f:
                            st.download_button(
                                label=f"📥 {fname}",
                                data=f,
                                file_name=fname,
                                mime=mime or "application/octet-stream",
                                key=dl_key,
                                use_container_width=True,
                            )
                    else:
                        st.caption("⚠️ 로컬에서 파일을 찾을 수 없습니다.")
                else:
                    st.caption("⚠️ 파일명이 없어 다운로드를 제공할 수 없습니다.")

            st.divider()


def _find_source_file(filename: str) -> Optional[str]:
    """past_documents / todo_documents의 모든 하위폴더를 재귀적으로 탐색"""
    if not filename:
        return None
    target_nfc = unicodedata.normalize("NFC", filename)

    search_dirs = [
        APP_DIR / "past_documents",
        APP_DIR / "todo_documents",
        Path.cwd() / "past_documents",
        Path.cwd() / "todo_documents",
    ]
    for d in search_dirs:
        try:
            if not d.exists() or not d.is_dir():
                continue
            for entry in d.rglob("*"):
                if entry.is_file():
                    if unicodedata.normalize("NFC", entry.name) == target_nfc:
                        return str(entry)
        except FileNotFoundError:
            continue
    return None

def _extract_source_filenames(contexts) -> List[str]:
    """컨텍스트 문서 목록에서 파일명만 중복 없이 추출 (dict/Document/str 모두 지원)"""
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
        # 1) dict
        if isinstance(d, dict):
            meta = d.get("metadata") or {}
            name = meta.get("filename") or _basename(meta.get("source", ""))
            if (not name) and (d.get("page_content") or d.get("content")):
                first = (d.get("page_content") or d.get("content") or "").splitlines()[0].strip()
                if first.lower().startswith("source"):
                    maybe = first.split(":", 1)[-1].strip()
                    name = _basename(maybe)
        else:
            # 2) Document (있다면)
            if LC_Document is not None and isinstance(d, LC_Document):
                meta = getattr(d, "metadata", {}) or {}
                name = meta.get("filename") or _basename(meta.get("source", ""))
                if (not name) and getattr(d, "page_content", ""):
                    first = d.page_content.splitlines()[0].strip()
                    if first.lower().startswith("source"):
                        maybe = first.split(":", 1)[-1].strip()
                        name = _basename(maybe)
            # 3) 문자열 표현
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
    """
    faiss_db/<slug>/<cohort>/index.faiss 구조에서 사용 가능한 cohort 목록을 스캔.
    """
    base = APP_DIR / "faiss_db" / slug
    out = []
    if base.exists():
        for p in base.iterdir():
            if p.is_dir() and (p / "index.faiss").exists():
                out.append(p.name)
    # 연도 내림차순 정렬(숫자 우선)
    try:
        out.sort(key=lambda x: int(x), reverse=True)
    except Exception:
        out.sort(reverse=True)
    return out

def _infer_default_cohort(student_id: Optional[str], cohorts: List[str]) -> int:
    """
    student_id에서 4자리 혹은 앞 2자리(→20YY)로 기본 연도 유추. 없으면 0.
    """
    if not cohorts:
        return 0
    if not student_id:
        return 0
    digits = "".join(ch for ch in str(student_id) if ch.isdigit())
    candidates = []
    if len(digits) >= 4:
        candidates.append(digits[:4])  # 2020, 2021 ...
    if len(digits) >= 2:
        yy = int(digits[:2])
        if 0 <= yy <= 99:
            candidates.append(f"20{yy:02d}")
    for c in candidates:
        if c in cohorts:
            return cohorts.index(c)
    return 0

def _strip_llm_source_lines(text: str) -> str:
    """
    LLM이 임의로 출력한 'Source:' 라인을 제거.
    실제 출처 표기는 contexts에서 추출해 아래에서 별도로 붙인다.
    """
    return re.sub(r"(?im)^\s*source\s*:\s*.*$", "", text).strip()

# ──────────────────────────────────────────────────────────────────────────────
# Main Page
# ──────────────────────────────────────────────────────────────────────────────
def second_page():
    st.header("Kyung Hee University's Regulations Chatbot")

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

    # --- 코호트(입학년도) 선택 (학부/대학원 시행세칙만) ---
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

    # (카테고리, 코호트) 키
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
            # 현재 (카테고리, 코호트) 히스토리만 리셋
            if "chat_histories" in st.session_state:
                st.session_state["chat_histories"][vs_key] = []
            st.session_state.pop("dialog_identifier", None)
            st.rerun()

    # 세션 상태 초기화
    st.session_state.setdefault("dialog_identifier", uuid.uuid4())
    st.session_state.setdefault("vector_stores", {})
    st.session_state.setdefault("chat_histories", {})

    # 히스토리 준비
    st.session_state["chat_histories"].setdefault(vs_key, [])

    # 벡터스토어 준비 (카테고리+코호트 별 1회 로드&캐시)
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

    # 이전 대화 렌더링(선택된 카테고리+코호트만)
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

                # 1) LLM이 임의로 출력한 Source 라인 제거
                answer = _strip_llm_source_lines(raw_answer)

                # 2) 상위 N개 컨텍스트를 '답변과의 겹침도'로 재정렬하여 선택
                TOPK_CONTEXTS = st.session_state.get("topk_ctx", 5) if "topk_ctx" in st.session_state else 5

                # (A) 전부 정규화
                coerced = [_coerce_ctx_item(d) for d in (contexts or [])]

                # (B) 겹침 점수로 정렬 (답변과 더 겹치는 스니펫이 앞에 오도록)
                coerced.sort(key=lambda c: _overlap_score(answer, c.get("snippet", "")), reverse=True)

                # (C) 최종 상위 N개만 사용
                coerced = coerced[:TOPK_CONTEXTS]

                # 3) 필터링된 상위 N개의 파일명만 Source 라인에 반영
                seen, source_files = set(), []
                for c in coerced:
                    name = (c.get("filename") or "").strip()
                    if name and name not in seen:
                        seen.add(name)
                        source_files.append(name)
                if source_files:
                    answer = f"{answer}\n\nSource: " + ", ".join(source_files)

                # 4) 화면 출력
                st.chat_message("AI").write(answer)

                # 5) 참고한 문서 조각(스니펫) 미리보기 — 정렬/슬라이스된 동일 리스트 사용!
                _render_context_previews(coerced, max_items=TOPK_CONTEXTS)

                # 히스토리 저장 (카테고리+코호트)
                st.session_state["chat_histories"][vs_key].append(HumanMessage(content=user_input))
                st.session_state["chat_histories"][vs_key].append(AIMessage(content=answer))

            st.session_state.run_id = cb.traced_runs[0].id if cb.traced_runs else None

    # --------- Feedback ---------
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
