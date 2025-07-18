from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate,MessagesPlaceholder
from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
import streamlit as st
from datetime import datetime


SYSTEM_PROMPT = (
    f"Today's date is {datetime.now().strftime('%Y-%m-%d')}.\n"
    "You are a Virtual Assistant dedicated solely to providing guidance on the regulations, internal rules, and guidelines of Kyung Hee University.\n"
    "About this Virtual Assistant:\n"
    "This Virtual Assistant provides answers based on the updated datasets of regulations, internal rules, and guidelines from Kyung Hee University's Regulation Management System. Reference: https://rule.khu.ac.kr/lmxsrv/main/main.do\n"
    "Below is important information about the data sources you may refer to when answering questions.\n"
    "The retrieved contexts consist of text excerpts from various regulations, internal rules, and guidelines managed by Kyung Hee University's Regulation Management System.\n"
    "On top of each context, there is a tag (e.g., (Academic Affairs)Regulation.pdf) that indicates its source.\n"
    "For example, 'Student_Affairs_Regulation.pdf' refers to the regulation document for student affairs, and 'Research_Guidelines.pdf' refers to the guideline document for research activities.\n"
    "You may choose to answer without using the context if it is unnecessary.\n"
    "However, if your answer is based on the context, you 'must' cite all the sources (noted at the beginning of each context) in your response such as 'Source: (Academic Affairs)Regulation.pdf and (Research)Guideline.txt'\n"
    "Make sure to provide sufficient explanation in your responses.\n"
    "Context:\n"
)


def get_vector_store():
    # Load a local FAISS vector store
    vector_store = FAISS.load_local(
        "./faiss_db/", 
        embeddings = OpenAIEmbeddings(model = "text-embedding-3-large"), 
        allow_dangerous_deserialization = True)
    
    return vector_store



def get_retreiver_chain(vector_store):

    llm = ChatOpenAI(model = "gpt-4o-mini", temperature = 0)

    faiss_retriever = vector_store.as_retriever(
       search_kwargs={"k": 5},
    )
    # bm25_retriever = BM25Retriever.from_documents(
    #    st.session_state.docs
    # )
    # bm25_retriever.k = 2

    # ensemble_retriever = EnsembleRetriever(
    #     retrievers = [bm25_retriever, faiss_retriever],
    # )

    prompt = ChatPromptTemplate.from_messages([
        MessagesPlaceholder(variable_name = "chat_history"),
        ("user","{input}"),
        ("user","Based on the conversation above, generate a search query that retrieves relevant information. Provide enough context in the query to ensure the correct document is retrieved. Only output the query.")
    ])
    history_retriver_chain = create_history_aware_retriever(llm, faiss_retriever, prompt)

    return history_retriver_chain




def get_conversational_rag(history_retriever_chain):
  # Create end-to-end RAG chain
  llm = ChatOpenAI(model = "gpt-4o-mini", temperature = 0)

  answer_prompt = ChatPromptTemplate.from_messages([
      ("system",SYSTEM_PROMPT+"\n\n{context}"),
      MessagesPlaceholder(variable_name = "chat_history"),
      ("user","{input}")
  ])

  document_chain = create_stuff_documents_chain(llm,answer_prompt)

  conversational_retrieval_chain = create_retrieval_chain(history_retriever_chain, document_chain)

  return conversational_retrieval_chain

