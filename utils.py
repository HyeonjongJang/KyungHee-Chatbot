# utils.py
from typing import Iterable
from langchain.schema import Document
import json, os

def save_docs_to_jsonl(docs: Iterable[Document], jsonl_path: str) -> None:
    os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
    with open(jsonl_path, 'w', encoding='utf-8', newline='\n') as jsonl_file:
        for doc in docs:
            # LangChain Document(Pydantic) 우선 사용
            try:
                s = doc.json(ensure_ascii=False)
            except Exception:
                # 예비 경로: dict/model_dump 가능성
                to_dict = getattr(doc, "dict", None) or getattr(doc, "model_dump", None)
                if callable(to_dict):
                    s = json.dumps(to_dict(), ensure_ascii=False)
                else:
                    s = json.dumps(
                        {
                            "page_content": getattr(doc, "page_content", str(doc)),
                            "metadata": getattr(doc, "metadata", {}),
                        },
                        ensure_ascii=False,
                    )
            jsonl_file.write(s + "\n")

def load_docs_from_jsonl(jsonl_path: str):
    items = []
    if not os.path.exists(jsonl_path):
        return items
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items
