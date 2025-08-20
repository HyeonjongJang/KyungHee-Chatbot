# --- add_document.py (full, drop-in replacement) ---
import os
import re
import shutil
import datetime
from pathlib import Path
from typing import List, Tuple, Optional

from dotenv import load_dotenv
from langchain_community.document_loaders import PDFMinerLoader, NotebookLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS

from utils import load_docs_from_jsonl, save_docs_to_jsonl

# 1) .env를 "파일 위치 기준"으로 확실히 로드 + 환경변수 덮어쓰기 허용
HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY가 설정되지 않았습니다. "
        ".env 파일을 add_document.py와 같은 폴더에 두고,"
        ' 내용은 OPENAI_API_KEY=sk-... (따옴표 없이) 형태로 작성하세요.'
    )

# 2) 임베딩 객체 생성 시 api_key를 명시 주입 (환경변수 인식 실패 대비)
EMBED_MODEL_NAME = "text-embedding-3-large"
EMBEDDINGS = OpenAIEmbeddings(model=EMBED_MODEL_NAME, api_key=OPENAI_API_KEY)

# -------------------------------------------------------------

def _clean_pdf_text(text: str) -> str:
    text = text.replace("\x0c", " ").replace("\n", " ")
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()

def _split_docs(docs) -> List:
    splitter = RecursiveCharacterTextSplitter(chunk_size=2048, chunk_overlap=256)
    return splitter.split_documents(docs)

def process_and_vectorize_file(file_path: Path, embedding_model: OpenAIEmbeddings):
    """파일 1개 로딩 → 청크화 → 메타데이터 보강 → 해당 파일의 FAISS 생성."""
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    # 문서 로딩
    if suffix == ".txt":
        loader = TextLoader(str(file_path))
        docs = loader.load()
    elif suffix == ".pdf":
        loader = PDFMinerLoader(str(file_path))
        docs = loader.load()
        if docs:
            docs[0].page_content = _clean_pdf_text(docs[0].page_content)
    elif suffix == ".ipynb":
        loader = NotebookLoader(str(file_path), include_outputs=False, remove_newline=True)
        docs = loader.load()
    else:
        # 지원하지 않는 확장자
        return [], None

    # 청크 분할
    splits = _split_docs(docs)

    # 메타데이터 보강 및 Source 프리픽스
    fname = os.path.basename(str(file_path))
    for d in splits:
        d.page_content = f"Source : {fname}\n{d.page_content}"
        d.metadata = d.metadata or {}
        d.metadata["filename"] = fname     # ← UI에서 파일명 직접 사용
        d.metadata.setdefault("source", str(file_path))  # 원본 경로(있으면 유지)

    if not splits:
        return [], None

    # 해당 파일만으로 부분 벡터스토어 생성
    vs = FAISS.from_documents(documents=splits, embedding=embedding_model)
    return splits, vs

def load_documents_process_vectorize(
    todo_documents_path: Path,
    past_documents_path: Path,
    embedding_model: OpenAIEmbeddings,
) -> Tuple[List, Optional[FAISS]]:
    """todo_documents의 모든 파일을 임베딩하고 past_documents로 이동."""
    todo_documents_path = Path(todo_documents_path)
    past_documents_path = Path(past_documents_path)
    past_documents_path.mkdir(parents=True, exist_ok=True)

    file_list = [f for f in sorted(todo_documents_path.iterdir()) if f.is_file()]
    total_files = len(file_list)

    all_splits = []
    merged_vs: Optional[FAISS] = None

    for idx, file_path in enumerate(file_list, 1):
        print(f"[{idx}/{total_files}] 임베딩 중: {file_path.name} ...")
        try:
            splits, vs = process_and_vectorize_file(file_path, embedding_model)
            if splits and vs:
                print(f"   → 분할 청크 개수: {len(splits)}")
                all_splits.extend(splits)
                if merged_vs is None:
                    merged_vs = vs
                else:
                    merged_vs.merge_from(vs)
            else:
                print("   → 건너뜀(분할 결과 없음 또는 임베딩 실패)")
        finally:
            # 성공/실패와 관계없이 처리 완료 파일을 past_documents로 이동
            dest = past_documents_path / file_path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(file_path), str(dest))
            except Exception as e:
                print(f"   → 이동 실패(무시): {e}")

    print("모든 파일 임베딩 완료.")
    return all_splits, merged_vs

def save(
    faiss_vectorstore_path: Path,
    doc_path: Path,
    backup_root: Path,
    new_vectorstore: Optional[FAISS],
    new_docs: List,
    embedding_model: OpenAIEmbeddings,
):
    """기존 인덱스/문서와 병합 + 백업 후 저장."""
    faiss_vectorstore_path = Path(faiss_vectorstore_path)
    doc_path = Path(doc_path)
    backup_root = Path(backup_root)

    faiss_vectorstore_path.mkdir(parents=True, exist_ok=True)
    doc_path.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)

    index_faiss = faiss_vectorstore_path / "index.faiss"
    index_pkl = faiss_vectorstore_path / "index.pkl"
    doc_jsonl = doc_path / "doc.jsonl"

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    backup_dir = backup_root / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 1) 기존 벡터스토어가 있으면 로드해서 병합
    existing_vs: Optional[FAISS] = None
    if index_faiss.exists() and index_pkl.exists():
        try:
            existing_vs = FAISS.load_local(
                str(faiss_vectorstore_path),
                embeddings=embedding_model,
                allow_dangerous_deserialization=True,
            )
        except Exception as e:
            print(f"[경고] 기존 인덱스 로드 실패(새로 생성): {e}")

        # 기존 인덱스 백업
        try:
            shutil.move(str(index_faiss), str(backup_dir / "index.faiss"))
            shutil.move(str(index_pkl), str(backup_dir / "index.pkl"))
        except Exception as e:
            print(f"[경고] 인덱스 백업 실패(무시): {e}")

    # 2) 벡터스토어 병합 로직
    final_vs: Optional[FAISS] = None
    if existing_vs and new_vectorstore:
        existing_vs.merge_from(new_vectorstore)
        final_vs = existing_vs
    elif existing_vs and not new_vectorstore:
        final_vs = existing_vs
    elif new_vectorstore and not existing_vs:
        final_vs = new_vectorstore
    else:
        print("[알림] 저장할 벡터스토어가 없습니다(새 문서도 없고 기존 인덱스도 없음).")
        final_vs = None  # 그대로 진행(문서 JSONL만 저장 가능)

    # 3) 벡터스토어 저장
    if final_vs:
        final_vs.save_local(str(faiss_vectorstore_path))
        print(f"벡터스토어 저장 완료 → {faiss_vectorstore_path}")
    else:
        print("벡터스토어 저장 생략.")

    # 4) 문서 JSONL 병합 + 백업
    docs_out = []
    if doc_jsonl.exists():
        try:
            past_docs = load_docs_from_jsonl(str(doc_jsonl))
            docs_out.extend(past_docs)
            shutil.move(str(doc_jsonl), str(backup_dir / "doc.jsonl"))
        except Exception as e:
            print(f"[경고] 기존 doc.jsonl 로드/백업 실패(무시): {e}")

    docs_out.extend(new_docs or [])
    save_docs_to_jsonl(docs_out, str(doc_jsonl))
    print(f"문서 JSONL 저장 완료 → {doc_jsonl}")
    print(f"백업 위치 → {backup_dir}")

# -------------------------------------------------------------

def main():
    todo_dir = HERE / "todo_documents"
    past_dir = HERE / "past_documents"
    faiss_dir = HERE / "faiss_db"
    docs_dir = HERE / "docs"
    backup_dir = HERE / "backup"

    # 폴더 생성
    past_dir.mkdir(parents=True, exist_ok=True)
    faiss_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 작업
    docs, new_vs = load_documents_process_vectorize(
        todo_documents_path=todo_dir,
        past_documents_path=past_dir,
        embedding_model=EMBEDDINGS,
    )
    save(
        faiss_vectorstore_path=faiss_dir,
        doc_path=docs_dir,
        backup_root=backup_dir,
        new_vectorstore=new_vs,
        new_docs=docs,
        embedding_model=EMBEDDINGS,
    )
    print("✅ 전체 파이프라인 완료")

if __name__ == "__main__":
    main()
