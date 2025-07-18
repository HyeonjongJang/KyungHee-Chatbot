# Kyung Hee University Regulations Search Virtual Assistant

## Overview

This Virtual Assistant delivers answers based on the latest regulations and internal guidelines from Kyung Hee University’s Regulation Management System.

> **Reference:**  
> [Kyung Hee University Regulation Management System](https://rule.khu.ac.kr/lmxsrv/main/main.do)

**Note:**  
This tool is exclusively for Kyung Hee University regulation searches. For official matters like academic schedules or graduation requirements, always consult original documents or directly contact university administration.

---

## Installation & Usage

### 1. Environment Setup

conda create -n langchain python=3.11
conda activate langchain
pip install -r requirements.txt

### 2. Build the Vector Database

- Create two folders: `past_documents` and `todo_documents`.
- Put regulation-related files (`.pdf`, `.ipynb`, `.txt`) into `todo_documents`.
- *To add more file types, edit the `load_documents_process_vectorize()` function in `add_document.py`.*
- Run `add_document.py` to build the vector database.
  - This creates `index.faiss` and `index.pkl` in the `faiss_db` directory.
- Processed files are automatically moved to `past_documents`.
- If a database already exists, previous files are backed up in the `backup/` folder.

### 3. System Prompt & Interface Customization

- Main prompt: `chains.py` (customize as needed).
- ID authentication: `first_page.py` (prevents unauthorized access).
- Adjust the welcome and instruction pages as needed.

### 4. Streamlit Secret Configuration

1. Make a `.streamlit` directory.
2. Add a `secrets.toml` file, for example:

LANGCHAIN_API_KEY = "your_langchain_api_key"
OPENAI_API_KEY = "your_openai_api_key"
student_ids = ["member1", "member2"]

### 5. Local Testing

streamlit run main.py

### 6. Deployment

- Upload to Streamlit Cloud.
- Register the secret keys in the Secrets UI in deployment settings.

---

## Usage Notice & Guidelines

- **Use only for regulation searches at Kyung Hee University. Do not use for other purposes.**
- There is a rate limit on GPT-4 use. Please be considerate to enable fair sharing.
- Accounts with abnormal or unauthorized usage may be restricted.
- Conversations may be stored for research, but IDs are anonymized.
  - **Do not enter personal identifiable information.**
- Responses may not always be fully accurate. Always double-check important details via official sources or the administration office.
- Using this Assistant means you agree to these terms.

---

## 📬 Contact

For any inquiries, please contact:

- **HYUNJONG JANG**
- 📧 lezelamu@naver.com
