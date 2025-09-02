# main.py

import streamlit as st

st.set_page_config(
    page_title="Kyung Hee Regulations Assistant",
    layout="centered",               # ← wide 대신 centered
    initial_sidebar_state="collapsed",
)

import os
from first_page import *
from second_page import *
from admin_page import *

os.environ["LANGCHAIN_API_KEY"] = st.secrets["LANGCHAIN_API_KEY"]
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGCHAIN_PROJECT"] = "Kyung Hee University's Regulations Search Assistant"


def main():
    # first_page에서 눌렀던 플래그로 바로 Admin 진입(선택)
    if st.session_state.get("nav_to_admin"):
        admin_page()
        return

    # 사이드바 네비게이션(원하면 유지)
    tab = st.sidebar.radio("Navigate", ["Chatbot", "Admin"], index=0)
    if tab == "Admin":
        admin_page()
        return

    # 기본 라우팅
    if "student_id" not in st.session_state:
        first_page()
    else:
        second_page()


if __name__ == "__main__":
    main()
