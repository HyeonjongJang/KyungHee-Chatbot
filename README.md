Kyung Hee University Regulations Search Virtual Assistant
Overview
This Virtual Assistant provides answers based on the latest regulations, internal rules, and guidelines from Kyung Hee University’s Regulation Management System.

Reference: Kyung Hee University Regulation Management System

Note:
This tool is exclusively for searching regulations of Kyung Hee University. For official information like academic schedules or graduation requirements, please always consult official documents or contact the university administration.

Installation & Usage
1. Environment Setup
bash
conda create -n langchain python=3.11
conda activate langchain
pip install -r requirements.txt
2. Build the Vector Database
Create two folders: past_documents and todo_documents.

Place regulation-related materials (.pdf, .ipynb, .txt) into todo_documents.

To support more file formats, modify load_documents_process_vectorize() in add_document.py.

Run add_document.py to build the vector database.

This will generate index.faiss and index.pkl in the faiss_db directory.

Processed files will be moved automatically to past_documents.

If the database exists, previous files are backed up in the backup/ folder.

3. System Prompt & Interface Customization
The main prompt is set in chains.py. Adapt it to match your institution’s requirements.

ID authentication is handled in first_page.py to prevent unauthorized access.

Adjust the welcome and instruction page as needed.

4. Streamlit Secret Configuration
Create a .streamlit directory.

Add a secrets.toml file:

text
LANGCHAIN_API_KEY = "your_langchain_api_key"
OPENAI_API_KEY = "your_openai_api_key"
student_ids = ["member1", "member2"]
5. Local Testing
bash
streamlit run main.py
6. Deployment
Upload to Streamlit Cloud.

Add the needed secret keys in the deployment setting’s Secrets UI.

Usage Notice & Guidelines
For regulation search only: Using this Assistant for any other purpose is not allowed.

There is a rate limit on GPT-4 usage. Use responsibly so everyone has fair access.

Accounts with abnormal or unauthorized usage may have access revoked.

Conversations may be stored and used for research; your member ID will be thoroughly anonymized.

Do not enter any personal identifiable information.

Answers may not always be accurate. For important matters, always check official sources or contact the administration office.

By using this Assistant, you agree to these terms and conditions.
