from pathlib import Path
from datetime import datetime
import streamlit as st

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from typing import Optional, Dict, Any

# RAG 시스템 프롬프트:
# - 템플릿/추론 문장 생성 시 “URI 없음/알 수 없음” 같은 플레이스홀더 금지
# - 근거가 없으면 섹션에 '-'로 남기고 “해당 조건의 결과가 없습니다.”만 출력하도록 지시
SYSTEM_PROMPT = (
    f"Today's date is {datetime.now().strftime('%Y-%m-%d')}.\n"
    "You are a Virtual Assistant for Kyung Hee University regulations.\n\n"
    "Priority Rules:\n"
    "1) When multiple versions exist, prefer the LATEST versionDate unless the user specifies otherwise.\n"
    "2) Prefer contexts that match the user's metadata intent (program, cohort, article/clause).\n"
    "3) If effectiveFrom/effectiveUntil appear to conflict with the user's context date, call this out explicitly.\n"
    "4) If no relevant context is retrieved, reply exactly with: '해당 조건의 결과가 없습니다.' and stop.\n\n"
    "Strict Output Rules:\n"
    "- NEVER fabricate URIs, articles, or clauses.\n"
    "- NEVER print placeholders like 'URI 없음' or '정보 없음'. Use '-' if unknown.\n"
    "- Each context chunk begins with a 'Source : <filename>' line. Do not fabricate sources.\n"
    "The UI will append exact source names automatically—do NOT add a separate citation section yourself.\n"
    "Context:\n"
)

# 구조화 섹션 템플릿
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

    prompt = ChatPromptTemplate.from_messages([
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{input}"),
        ("user",
         "Based on the conversation above, generate a search query that retrieves relevant information. "
         "Provide enough context in the query to ensure the correct document is retrieved. Only output the query.")
    ])
    history_retriever_chain = create_history_aware_retriever(llm, faiss_retriever, prompt)
    return history_retriever_chain

# 오타 호환
get_retriever_chain = get_retreiver_chain

# ── End-to-end Conversational RAG ────────────────────────────────────────────
def get_conversational_rag(history_retriever_chain):
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    answer_prompt = ChatPromptTemplate.from_messages([
        ("system",
         SYSTEM_PROMPT
         + "\n\n{context}\n\n"
         "Return your answer using the following Korean sections. "
         "If a value is unknown, write '-' and keep the section:\n"
         "- 결론: 핵심 답 1~2문장.\n"
         "- 적용 버전: versionDate와 효력 기간(가능하면).\n"
         "- 근거: “제N조 (제M항)”와 URI(있으면)를 대괄호로.\n"
         "- 예외 사항: 있다면 짧게.\n"
         "- 주의: 버전 충돌·효력기간 이슈가 있으면 짧게.\n\n"
         "Use this exact format template:\n"
         + ANSWER_FORMAT
        ),
        MessagesPlaceholder(variable_name="chat_history"),
        ("user", "{input}")
    ])

    document_chain = create_stuff_documents_chain(llm, answer_prompt)
    conversational_retrieval_chain = create_retrieval_chain(history_retriever_chain, document_chain)
    return conversational_retrieval_chain
