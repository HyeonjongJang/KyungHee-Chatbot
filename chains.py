from pathlib import Path
from datetime import datetime
import streamlit as st

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
# from langchain_community.retrievers import BM25Retriever
# from langchain.retrievers import EnsembleRetriever
from typing import Optional


SYSTEM_PROMPT = (
    f"Today's date is {datetime.now().strftime('%Y-%m-%d')}.\n"
    "You are a Virtual Assistant dedicated solely to providing guidance on the regulations, internal rules, and guidelines of Kyung Hee University.\n"
    "This assistant retrieves short context snippets from KHU's Regulation Management System.\n"
    "Each context chunk begins with a 'Source : <filename>' line that indicates its origin.\n"
    "Do not fabricate or guess source names. You do NOT need to write a 'Source:' section yourself; the application will append the exact sources automatically.\n"
    "If context is used, focus on answering clearly and completely. Avoid adding extra citation text in your answer.\n"
    "Context:\n"
)


# ── Vector store loader (category + optional cohort) ─────────────────────────
def get_vector_store(category_slug: str, cohort: Optional[str] = None) -> FAISS:
    """
    카테고리(+코호트)별 FAISS 로드
    - 규정/학사제도: cohort=None → faiss_db/<category>/
    - 학부/대학원 시행세칙: cohort='2020' 등 → faiss_db/<category>/<cohort>/
    * 요구사항상 '코호트 강제'이므로, 요청 경로에 인덱스가 없으면 에러를 던집니다.
    """
    base = Path("./faiss_db") / category_slug
    if cohort:
        base = base / str(cohort)
    index_path = base / "index.faiss"
    if not index_path.exists():
        target = f"{category_slug}/{cohort}" if cohort else category_slug
        raise FileNotFoundError(f"FAISS index not found for: {target}")
    return FAISS.load_local(
        str(base),
        embeddings=OpenAIEmbeddings(model="text-embedding-3-large"),
        allow_dangerous_deserialization=True,
    )


# ── Retriever (history-aware) ────────────────────────────────────────────────
def get_retreiver_chain(vector_store: FAISS):
    """
    대화 히스토리를 반영해, 사용자 입력을 검색쿼리로 바꿔주는 history-aware retriever 체인.
    """
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    faiss_retriever = vector_store.as_retriever(
        search_kwargs={"k": 5},
    )
    # 필요시 BM25 + Ensemble 활성화:
    # bm25_retriever = BM25Retriever.from_documents(st.session_state.docs)
    # bm25_retriever.k = 2
    # ensemble_retriever = EnsembleRetriever(retrievers=[bm25_retriever, faiss_retriever])

    prompt = ChatPromptTemplate.from_messages([
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{input}"),
        ("user", "Based on the conversation above, generate a search query that retrieves relevant information. "
                 "Provide enough context in the query to ensure the correct document is retrieved. Only output the query.")
    ])
    history_retriever_chain = create_history_aware_retriever(llm, faiss_retriever, prompt)
    return history_retriever_chain

# 오타 호환용 별칭 (원래 이름을 그대로 쓰는 코드가 있을 수 있으므로 유지)
get_retriever_chain = get_retreiver_chain


# ── End-to-end Conversational RAG ────────────────────────────────────────────
def get_conversational_rag(history_retriever_chain):
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    answer_prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT + "\n\n{context}"),
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{input}")
    ])

    document_chain = create_stuff_documents_chain(llm, answer_prompt)
    conversational_retrieval_chain = create_retrieval_chain(history_retriever_chain, document_chain)
    return conversational_retrieval_chain