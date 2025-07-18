Kyung Hee University Regulations Search Virtual Assistant
🧾 Overview
This Virtual Assistant provides answers based on the most up-to-date datasets of regulations, internal rules, and guidelines from Kyung Hee University's Regulation Management System.

Reference: Kyung Hee University Regulation Management System

This tool is provided exclusively for regulation search within Kyung Hee University. For important information such as academic schedules or graduation requirements, always verify with official documents or by contacting the university administration office.

⚙️ Installation & Usage
1. Environment Setup
bash
conda create -n langchain python=3.11
conda activate langchain
pip install -r requirements.txt
2. Building the Vector Database
Create two folders: past_documents and todo_documents.

Place regulation-related materials (.pdf, .ipynb, .txt) in todo_documents.

Adding more file formats: Edit the load_documents_process_vectorize() function in add_document.py.

Run add_document.py to build the vector database.

The index.faiss and index.pkl files will be created in the faiss_db directory.

Files are automatically moved to past_documents after processing.

If a database already exists, previous files are backed up in the backup/ folder with the current timestamp.

3. System Prompt & Interface Customization
The base system prompt is defined in chains.py. Adapt this to suit your institution’s policies if necessary.

User (student/member) ID authentication is implemented in first_page.py to prevent unauthorized access via public links.

You may customize the welcome and instructions page to match the notice below.

4. Streamlit Secret Configuration
Create a .streamlit directory and a file named secrets.toml as below:

text
LANGCHAIN_API_KEY = "your_langchain_api_key"
OPENAI_API_KEY = "your_openai_api_key"
student_ids = ["member1", "member2"]
5. Local Testing
bash
streamlit run main.py
6. Deployment
Upload the repository to Streamlit Cloud.

Use the Secrets configuration UI in deployment settings to add the required keys as above.

🛑 Usage Notice & Important Guidelines
This Assistant is strictly for Kyung Hee University regulations search.
Use for any other purpose is prohibited.

There is a rate limit on GPT-4 usage. Please be considerate to ensure all users have fair access.

Accounts found to be using this tool for non-regulation purposes or with abnormal usage patterns may have access revoked.

Conversations with the Assistant will be stored and used for research purposes; however, your member ID will be thoroughly anonymized.
Do not include any personally identifiable information (PII) in your conversations.

The model may occasionally provide inaccurate answers. For critical university rules or policies (e.g., academic schedule, graduation requirements), please confirm through official sources or directly contact the administration office.

By using this Assistant, you agree to these terms and conditions.

📬 Contact
For any inquiries, please contact:

HYUNJONG JANG

📧 lezelamu@naver.com

Reference
Kyung Hee University Regulation Management System: https://rule.khu.ac.kr/lmxsrv/main/main.do
