# --- second_page.py ---
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

# 앱 기준 디렉터리(엔트리 스크립트와 같은 폴더에 past_documents, todo_documents가 있어야 함)
APP_DIR = Path(__file__).resolve().parent


def _basename_crossplat(p: str) -> str:
    """
    윈도우/리눅스 경로 구분자 모두 처리해 파일명만 추출 + 한글 정규화(NFC).
    메타데이터에 'todo_documents\\파일.pdf' 같이 백슬래시가 들어간 경우를 안전하게 처리.
    """
    if not p:
        return ""
    p = p.strip().strip('"').strip("'")
    name = ntpath.basename(p)  # 백슬래시(\) 지원
    # 혹시 남은 슬래시를 한 번 더 정리
    name = name.split("/")[-1].split("\\")[-1]
    return unicodedata.normalize("NFC", name)


def _find_source_file(filename: str) -> Optional[str]:
    """
    past_documents 우선, 없으면 todo_documents에서 파일 존재 여부 확인.
    대/소문자 및 한글 정규화(NFC)까지 맞춰서 비교.
    """
    if not filename:
        return None
    target_nfc = unicodedata.normalize("NFC", filename)

    search_dirs = [
        APP_DIR / "past_documents",
        APP_DIR / "todo_documents",
        Path.cwd() / "past_documents",   # 혹시 CWD가 다른 환경도 커버
        Path.cwd() / "todo_documents",
    ]

    for d in search_dirs:
        try:
            if not d.exists() or not d.is_dir():
                continue
            for entry in d.iterdir():
                if entry.is_file():
                    if unicodedata.normalize("NFC", entry.name) == target_nfc:
                        return str(entry)
        except FileNotFoundError:
            continue
    return None


def _extract_source_filenames(contexts) -> List[str]:
    """
    RAG 응답의 context(문서 청크들)에서 파일명을 추출.
    우선순위:
      1) d.metadata["filename"] (있다면 가장 신뢰)
      2) d.metadata["source"] 경로에서 파일명만 추출
      3) d.page_content 첫 줄 'Source : 파일명' 프리픽스 파싱(백업)
    """
    seen, out = set(), []
    for d in contexts or []:
        meta = getattr(d, "metadata", {}) or {}
        # 1순위: 명시적 파일명 메타데이터
        name = meta.get("filename")

        # 2순위: 원본 경로에서 파일명만 추출
        if not name:
            name = _basename_crossplat(meta.get("source", ""))

        # 3순위(백업): 본문 프리픽스에서 파싱
        if (not name) and getattr(d, "page_content", ""):
            first = d.page_content.splitlines()[0].strip()
            if first.lower().startswith("source"):
                # e.g., "Source : 2025년 인공지능학과.pdf"
                maybe = first.split(":", 1)[-1].strip()
                name = _basename_crossplat(maybe)

        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def second_page():
    st.header("Kyung Hee University's Regulations Chatbot")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Go to Home", key="home_page"):
            st.session_state.pop("student_id", None)
            st.session_state.pop("chat_history", None)
            st.session_state.pop("dialog_identifier", None)
            st.rerun()
    with col2:
        if st.button("Refresh", key="refresh"):
            st.session_state.pop("chat_history", None)
            st.session_state.pop("dialog_identifier", None)
            st.rerun()

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "vector_store" not in st.session_state:
        st.session_state.vector_store = get_vector_store()
    if "dialog_identifier" not in st.session_state:
        st.session_state.dialog_identifier = uuid.uuid4()

    # 이전 대화 렌더링
    for message in st.session_state.chat_history:
        if isinstance(message, AIMessage):
            with st.chat_message("AI"):
                st.write(message.content)
        else:
            with st.chat_message("Human"):
                st.write(message.content)

    def get_response(user_input):
        history_retriever_chain = get_retreiver_chain(st.session_state.vector_store)
        conversation_rag_chain = get_conversational_rag(history_retriever_chain)
        response = conversation_rag_chain.invoke(
            {
                "chat_history": st.session_state.chat_history,
                "input": user_input,
                "student_id": st.session_state.get("student_id"),
                "dialog_identifier": st.session_state.dialog_identifier,
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

                # 📎 출처 문서 다운로드
                source_files = _extract_source_filenames(contexts)
                if source_files:
                    with st.expander("📎 출처 문서 다운로드"):
                        for fname in source_files:
                            found_path = _find_source_file(fname)  # ← 경로 결정
                            if found_path and os.path.exists(found_path):
                                mime, _ = mimetypes.guess_type(fname)
                                with open(found_path, "rb") as f:
                                    st.download_button(
                                        label=f"📥 {fname}",
                                        data=f,
                                        file_name=fname,
                                        mime=mime or "application/octet-stream",
                                        key=f"dl_{fname}_{st.session_state.dialog_identifier}",
                                    )
                            else:
                                st.caption(f"⚠️ 파일을 찾을 수 없습니다: {fname}")

                # 대화 히스토리 저장
                st.session_state.chat_history.append(HumanMessage(content=user_input))
                st.session_state.chat_history.append(AIMessage(content=answer))

            # run_id 저장 (feedback 용)
            st.session_state.run_id = cb.traced_runs[0].id

    # --------- Feedback ---------
    feedback_option = "thumbs"
    if st.session_state.get("run_id"):
        run_id = st.session_state.run_id
        feedback = streamlit_feedback(
            feedback_type="thumbs",
            optional_text_label="[Optional] Please provide an explanation",
            key=f"feedback_{run_id}",
        )

        score_mappings = {
            "thumbs": {"👍": 1, "👎": -1},
            "faces": {"😀": 1, "🙂": 0.75, "😐": 0.5, "🙁": 0.25, "😞": 0},
        }
        scores = score_mappings[feedback_option]

        if feedback:
            score = scores.get(feedback["score"])
            if score is not None:
                feedback_type_str = f"{feedback_option} {feedback['score']}"
                feedback_record = client.create_feedback(
                    run_id,
                    feedback_type_str,
                    score=score,
                    comment=feedback.get("text"),
                )
                st.session_state.feedback = {
                    "feedback_id": str(feedback_record.id),
                    "score": score,
                }
            else:
                st.warning("Invalid feedback score.")