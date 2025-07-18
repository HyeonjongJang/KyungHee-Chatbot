# A Large-Scale Real-World Evaluation of an LLM-Based Virtual Assistant

[ACL 2025 Industry Track]  
Official code repository for:  
**"A Large-Scale Real-World Evaluation of an LLM-Based Virtual Assistant"**

---

## 🧾 Abstract

Virtual Assistants (VTAs) powered by Large Language Models (LLMs) have the potential to enhance student learning by providing instant feedback and facilitating multi-turn interactions. However, empirical studies on their effectiveness and acceptance in real-world classrooms are limited, leaving their practical impact uncertain. In this study, we develop an LLM-based Virtual Assistant and deploy it in an introductory
AI programming course with 477 graduate students. To assess how student perceptions of the Virtual Assistant’s performance evolve over time, we conduct three rounds of comprehensive surveys at different stages of the course. Additionally, we analyze 3,869 student–VTA interaction pairs to identify common question types and engagement patterns. We then compare these interactions with traditional student-human instructor interactions to evaluate the Virtual Assistant’s role in the learning process. Through a large-scale empirical study and interaction analysis, we assess the feasibility of deploying VTAs in real-world classrooms and identify key challenges for broader adoption. Finally, we release the source code of our VTA system, fostering future advancements in AI-driven education.

---

## ⚙️ Requirements

```bash
conda create -n langchain python=3.11
conda activate langchain
pip install -r requirements.txt
```

---

## 🚀 How to Use

### 1. Building the Vector Database

- Create two folders: `past_documents` and `todo_documents`.
- Put course materials to be embedded into `todo_documents`.
  - Supported file types: `.pdf`, `.ipynb`, `.txt`
  - To support additional formats, modify `load_documents_process_vectorize()` in `add_document.py`.
- Run `add_document.py` to create the vector DB. This generates `index.faiss` and `index.pkl` in the `faiss_db` directory.
- Files in `todo_documents` are automatically moved to `past_documents`.
- When new materials are added (e.g., weekly), place them in `todo_documents` and rerun the script.
- If an existing DB is found, previous files are backed up in the `backup/` folder with the current timestamp.

### 2. System Prompt Customization

- The system prompt used in the Kyung Hee University's Regulations Search Assistant course is defined in `chains.py`.
- Update this prompt to fit your own course or institution-specific context.

### 3. Retriever Configuration

- The default retriever is FAISS-based dense retriever with `k=5` documents returned.
- To change the retriever (e.g., sparse vectors) or the number of documents, modify the `get_retriever_chain()` function in `chains.py`.

### 4. First Page Customization

- The first interface (`first_page.py`) includes a student ID verification step.
- This prevents unauthorized users from accessing the assistant via public links (e.g., Streamlit Cloud).
- Only users with IDs matching the internal list can proceed to the chatbot.
- You can customize the content and instructions shown on this page for your class.

### 5. Streamlit Secret Configuration

- Create a `.streamlit` directory and add a file named `secrets.toml`.
- Inside `secrets.toml`, insert the following (with your own keys and student list):

```toml
LANGCHAIN_API_KEY = "your_langchain_api_key"
OPENAI_API_KEY = "your_openai_api_key"
student_ids = ["student1", "student2"]
```

### 6. Local Testing

To test the assistant locally, run:

```bash
streamlit run main.py
```

### 7. Deployment

- Upload the repository to [Streamlit Cloud](https://streamlit.io/cloud).
- In the deployment settings, add the required secret keys (same as in `secrets.toml`) through Streamlit’s **"Secrets"** configuration UI.

---

## 📬 Contact

For any inquiries, please contact:

**Sunjun Kweon**  
📧 sean0042@kaist.ac.kr