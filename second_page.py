# --- second_page.py ---
import os
import mimetypes
import streamlit as st
from chains import get_vector_store, get_retreiver_chain, get_conversational_rag
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tracers.context import collect_runs
from langsmith import Client
from streamlit_feedback import streamlit_feedback
# from utils import load_docs_from_jsonl  # (필요시)
# from langchain_community.document_loaders.csv_loader import CSVLoader  # (미사용)

import uuid

client = Client()

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
        response = conversation_rag_chain.invoke({
            "chat_history": st.session_state.chat_history,
            "input": user_input,
            "student_id": st.session_state.student_id,
            "dialog_identifier": st.session_state.dialog_identifier
        })
        answer = response["answer"]  # 기존 그대로
        # 🔽 추가: 이번 답변에 사용된 문서 청크들
        contexts = response.get("context", [])
        # 문서별 원본 파일명(중복 제거, 순서 유지)
        seen = set()
        source_files = []
        for d in contexts:
            src = d.metadata.get("source")  # loader가 채운 원본 경로
            if src:
                name = os.path.basename(src)
                if name not in seen:
                    seen.add(name)
                    source_files.append(name)
        return answer, source_files

    if user_input := st.chat_input("Type your message here..."):
        st.chat_message("Human").write(f"{user_input}")

        with collect_runs() as cb:
            with st.spinner("Thinking..."):
                answer, source_files = get_response(user_input)
                st.chat_message("AI").write(answer)

                # 🔽 추가: 출처 문서 다운로드 UI
                if source_files:
                    with st.expander("📎 출처 문서 다운로드"):
                        for fname in source_files:
                            path = None
                            # 파일은 add_document가 끝나면 past_documents로 이동됩니다. :contentReference[oaicite:1]{index=1}
                            for base in ("past_documents", "todo_documents"):
                                candidate = os.path.join(base, fname)
                                if os.path.exists(candidate):
                                    path = candidate
                                    break
                            if path:
                                mime, _ = mimetypes.guess_type(fname)
                                with open(path, "rb") as f:
                                    st.download_button(
                                        label=f"📥 {fname}",
                                        data=f,
                                        file_name=fname,
                                        mime=mime or "application/octet-stream",
                                        key=f"dl_{fname}_{st.session_state.dialog_identifier}",
                                    )
                            else:
                                st.caption(f"⚠️ 파일을 찾을 수 없습니다: {fname}")

                st.session_state.chat_history.append(HumanMessage(content=user_input))
                st.session_state.chat_history.append(AIMessage(content=answer))
            st.session_state.run_id = cb.traced_runs[0].id

    # (이하 feedback 코드는 기존 그대로)



    feedback_option = "thumbs"
    if st.session_state.get("run_id"):
        run_id = st.session_state.run_id
        feedback = streamlit_feedback(
            feedback_type = "thumbs",
            optional_text_label ="[Optional] Please provide an explanation",
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
                    score = score,
                    comment=feedback.get("text"),
                )
                st.session_state.feedback = {
                    "feedback_id": str(feedback_record.id),
                    "score": score,
                }
            else:
                st.warning("Invalid feedback score.")