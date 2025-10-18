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
from typing import Optional, Dict, Any


SYSTEM_PROMPT = (
    f"Today's date is {datetime.now().strftime('%Y-%m-%d')}.\n"
    "You are a Virtual Assistant for Kyung Hee University regulations.\n\n"
    "Priority Rules:\n"
    "1) When multiple versions exist, prefer the LATEST versionDate unless the user specifies otherwise.\n"
    "2) Prefer contexts that match the user's metadata intent (program, cohort, article/clause).\n"
    "3) If effectiveFrom/effectiveUntil appear to conflict with the user's context date, call this out explicitly.\n"
    "4) (Future) If SPARQL/KG results are provided, those numeric/decision values override text snippets.\n\n"
    "Each context chunk begins with a 'Source : <filename>' line. Do not fabricate sources.\n"
    "The UI will append exact source names automatically—do NOT add a separate citation section yourself.\n"
    "Context:\n"
)

# ── 구조화 출력 포맷(안내용 텍스트) ──────────────────────────────────────────────
ANSWER_FORMAT = (
    "**결론:** {final_answer}\n"
    "**적용 버전:** {version_date} (효력: {effective_from} ~ {effective_until})\n"
    "**근거:** 제{article_num}조{clause_part} [{uri_part}]\n"
    "**예외 사항:** {exceptions}\n"
    "**주의:** {notices}\n"
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
def get_retreiver_chain(vector_store: FAISS, meta_filter: Optional[Dict[str, Any]] = None, top_k: int = 5):
    """
    대화 히스토리를 반영해, 사용자 입력을 검색쿼리로 바꿔주는 history-aware retriever 체인.
    """
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    skw = {"k": int(top_k)}
    if meta_filter:
        skw["filter"] = {k: v for k, v in meta_filter.items() if v not in (None, "", [])}
    faiss_retriever = vector_store.as_retriever(search_kwargs=skw)
    # 필요시 BM25 + Ensemble 활성화:
    # bm25_retriever = BM25Retriever.from_documents(st.session_state.docs)
    # bm25_retriever.k = 2
    # ensemble_retriever = EnsembleRetriever(retrievers=[bm25_retriever, faiss_retriever])

    prompt = ChatPromptTemplate.from_messages([
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{input}"),
        ("user",
         "Based on the conversation above, generate a search query that retrieves relevant information. "
         "Provide enough context in the query to ensure the correct document is retrieved. Only output the query.")
    ])
    history_retriever_chain = create_history_aware_retriever(llm, faiss_retriever, prompt)
    return history_retriever_chain

# 오타 호환용 별칭 (원래 이름을 그대로 쓰는 코드가 있을 수 있으므로 유지)
get_retriever_chain = get_retreiver_chain


# ── End-to-end Conversational RAG ────────────────────────────────────────────
def get_conversational_rag(history_retriever_chain):
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # 답변 프롬프트: 구조화 섹션 지시 + ANSWER_FORMAT 예시 포함
    answer_prompt = ChatPromptTemplate.from_messages([
        ("system",
         SYSTEM_PROMPT
         + "\n\n{context}\n\n"
         "Return your answer using the following Korean sections. "
         "If a value is unknown, write '-' and keep the section:\n"
         "- 결론: 핵심 답을 1~2문장으로.\n"
         "- 적용 버전: versionDate와 효력 기간(가능하면).\n"
         "- 근거: “제N조 (제M항)”와 URI(있으면)를 대괄호로.\n"
         "- 예외 사항: 예외가 있으면 짧게.\n"
         "- 주의: 버전 충돌·효력기간 이슈가 있으면 짧게.\n\n"
         "Use this exact format template (fill the braces with values; leave '-' if unknown):\n"
         + ANSWER_FORMAT
        ),
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{input}")
    ])

    document_chain = create_stuff_documents_chain(llm, answer_prompt)
    conversational_retrieval_chain = create_retrieval_chain(history_retriever_chain, document_chain)
    return conversational_retrieval_chain
