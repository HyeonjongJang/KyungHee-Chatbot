# --- second_page.py (drop-in) ---
import os
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

def _basename_crossplat(p: str) -> str:
    if not p:
        return ""
    p = p.strip().strip('"').strip("'")
    name = ntpath.basename(p)
    name = name.split("/")[-1].split("\\")[-1]
    return unicodedata.normalize("NFC", name)

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
    seen, out = set(), []
    for d in contexts or []:
        meta = getattr(d, "metadata", {}) or {}
        name = meta.get("filename")
        if not name:
            name = _basename_crossplat(meta.get("source", ""))
        if (not name) and getattr(d, "page_content", ""):
            first = d.page_content.splitlines()[0].strip()
            if first.lower().startswith("source"):
                maybe = first.split(":", 1)[-1].strip()
                name = _basename_crossplat(maybe)
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out

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

    # 상단 버튼
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Go to Home", key="home_page"):
            st.session_state.pop("student_id", None)
            st.session_state.pop("chat_histories", None)
            st.session_state.pop("vector_stores", None)
            st.session_state.pop("dialog_identifier", None)
            st.rerun()
    with col2:
        if st.button("Refresh", key="refresh"):
            # 현재 카테고리의 히스토리만 리셋
            if "chat_histories" in st.session_state:
                st.session_state["chat_histories"][sel_slug] = []
            st.session_state.pop("dialog_identifier", None)
            st.rerun()

    # 세션 상태 초기화
    st.session_state.setdefault("dialog_identifier", uuid.uuid4())
    st.session_state.setdefault("vector_stores", {})
    st.session_state.setdefault("chat_histories", {})

    # 카테고리 변경 시 히스토리/상태 준비
    st.session_state["chat_histories"].setdefault(sel_slug, [])

    # 벡터스토어 준비 (카테고리별 1회 로드&캐시)
    vs = st.session_state["vector_stores"].get(sel_slug)
    if (vs is None) or changed_category:
        try:
            vs = get_vector_store(sel_slug)
            st.session_state["vector_stores"][sel_slug] = vs
        except FileNotFoundError:
            st.error(f"선택한 범주('{sel_label}')에 대한 벡터 DB가 없습니다. 먼저 add_document.py로 구축해 주세요.")
            return

    # 이전 대화 렌더링(선택된 카테고리만)
    for message in st.session_state["chat_histories"][sel_slug]:
        role = "AI" if isinstance(message, AIMessage) else "Human"
        with st.chat_message("AI" if role == "AI" else "Human"):
            st.write(message.content)

    def get_response(user_input):
        history_retriever_chain = get_retreiver_chain(vs)
        conversation_rag_chain = get_conversational_rag(history_retriever_chain)
        response = conversation_rag_chain.invoke(
            {
                "chat_history": st.session_state["chat_histories"][sel_slug],
                "input": user_input,
                "student_id": st.session_state.get("student_id"),
                "dialog_identifier": st.session_state["dialog_identifier"],
            }
        )
        answer = response["answer"]
        contexts = response.get("context", [])
        return answer, contexts

    if user_input := st.chat_input("Type your message here..."):
        st.chat_message("Human").write(user_input)

        with collect_runs() as cb:
            with st.spinner("Thinking..."):
                answer, contexts = get_response(user_input)
                st.chat_message("AI").write(answer)

                # 📎 출처 문서 다운로드 (하위폴더 포함)
                source_files = _extract_source_filenames(contexts)
                if source_files:
                    with st.expander("📎 출처 문서 다운로드"):
                        for fname in source_files:
                            found_path = _find_source_file(fname)
                            if found_path and os.path.exists(found_path):
                                mime, _ = mimetypes.guess_type(fname)
                                with open(found_path, "rb") as f:
                                    st.download_button(
                                        label=f"📥 {fname}",
                                        data=f,
                                        file_name=fname,
                                        mime=mime or "application/octet-stream",
                                        key=f"dl_{fname}_{st.session_state['dialog_identifier']}",
                                    )
                            else:
                                st.caption(f"⚠️ 파일을 찾을 수 없습니다: {fname}")

                # 카테고리별 히스토리 저장
                st.session_state["chat_histories"][sel_slug].append(HumanMessage(content=user_input))
                st.session_state["chat_histories"][sel_slug].append(AIMessage(content=answer))

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
