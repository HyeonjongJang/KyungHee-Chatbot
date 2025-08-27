# add_document.py  (cohort-ready drop-in)
import os, re, shutil, argparse, datetime, math
from pathlib import Path
from typing import List, Tuple, Optional

from dotenv import load_dotenv
from langchain_community.document_loaders import PDFMinerLoader, NotebookLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS

from utils import load_docs_from_jsonl, save_docs_to_jsonl

load_dotenv()

CATEGORIES = {
    "regulations":       "규정",
    "undergrad_rules":   "학부 시행세칙",
    "grad_rules":        "대학원 시행세칙",
    "academic_system":   "학사제도",
}

# ── 경로 베이스 ────────────────────────────────────────────────────────────────
BASE         = Path(".")
FAISS_BASE   = BASE / "faiss_db"
TODO_BASE    = BASE / "todo_documents"
PAST_BASE    = BASE / "past_documents"
DOCS_BASE    = BASE / "docs"
BACKUP_BASE  = BASE / "backup"

SUPPORTED_EXTS = {".pdf", ".txt", ".ipynb"}

# ── 파일 로더 ────────────────────────────────────────────────────────────────
def _load_file(path: Path):
    if path.suffix.lower() == ".txt":
        return TextLoader(str(path)).load()
    if path.suffix.lower() == ".pdf":
        docs = PDFMinerLoader(str(path)).load()
        for d in docs:
            d.page_content = d.page_content.replace("\x0c", " ").replace("\n", " ")
            d.page_content = re.sub(r"\s{2,}", " ", d.page_content).strip()
        return docs
    if path.suffix.lower() == ".ipynb":
        return NotebookLoader(str(path), include_outputs=False, remove_newline=True).load()
    return []

def _split_docs(docs):
    splitter = RecursiveCharacterTextSplitter(chunk_size=2048, chunk_overlap=256)
    return splitter.split_documents(docs)

def _gather_files(todo_dir: Path) -> List[Path]:
    if not todo_dir.exists():
        return []
    return [p for p in todo_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]

# ── 배치 인덱스 생성(메모리 안전) ─────────────────────────────────────────────
def _build_index_in_batches(splits, emb, docs_per_batch: int = 32) -> Optional[FAISS]:
    total = len(splits)
    if total == 0:
        return None
    vs_local = None
    num_batches = math.ceil(total / docs_per_batch)
    for bi in range(num_batches):
        start = bi * docs_per_batch
        end   = min(start + docs_per_batch, total)
        batch = splits[start:end]
        print(f"   → 인덱스 배치 {bi+1}/{num_batches} (문서 {len(batch)}개)")
        if vs_local is None:
            vs_local = FAISS.from_documents(batch, embedding=emb)
        else:
            vs_local.add_documents(batch)
    return vs_local

# ── 카테고리(+코호트) 처리 ────────────────────────────────────────────────────
def _process_category(category_slug: str, cohort: Optional[str] = None) -> Tuple[list, Optional[FAISS]]:
    """
    주어진 카테고리(필수)와 코호트(선택)에 대해 todo_documents에서 파일을 읽어
    분할 → 임베딩 → 벡터스토어(FAISS) 생성까지 수행.
    """
    emb = OpenAIEmbeddings(model="text-embedding-3-large")

    # 코호트가 주어지면 하위 폴더 사용 (undergrad_rules/grad_rules용)
    todo_dir = TODO_BASE / category_slug / cohort if cohort else TODO_BASE / category_slug
    past_dir = PAST_BASE / category_slug / cohort if cohort else PAST_BASE / category_slug
    past_dir.mkdir(parents=True, exist_ok=True)

    files = _gather_files(todo_dir)
    total = len(files)
    if total == 0:
        label = f"{CATEGORIES[category_slug]} | {category_slug}" + (f" | cohort={cohort}" if cohort else "")
        print(f"[{label}] 처리할 파일이 없습니다: {todo_dir}")
        return [], None

    all_splits = []
    for idx, f in enumerate(sorted(files), 1):
        print(f"[{idx}/{total}] 임베딩 중: {f.relative_to(todo_dir)}")
        try:
            docs = _load_file(f)
            if not docs:
                print("   → 건너뜀(로더가 문서를 읽지 못함)")
                shutil.move(str(f), str(past_dir / f.name))
                continue
            splits = _split_docs(docs)
            for d in splits:
                d.page_content = "Source : " + f.name + "\n" + d.page_content
                meta = d.metadata or {}
                meta["filename"] = f.name
                meta["category"] = category_slug
                if cohort:
                    meta["cohort"] = cohort
                d.metadata = meta
            if not splits:
                print("   → 건너뜀(분할 결과 없음)")
            else:
                print(f"   → 분할 청크 개수: {len(splits)}")
                all_splits.extend(splits)
        finally:
            try:
                shutil.move(str(f), str(past_dir / f.name))
            except Exception as e:
                print(f"   → 이동 실패: {e}")

    if not all_splits:
        print(f"[{CATEGORIES[category_slug]}] 생성된 청크가 없습니다. 인덱스를 저장하지 않습니다.")
        return [], None

    vs_new = _build_index_in_batches(all_splits, emb, docs_per_batch=32)
    return all_splits, vs_new

# ── 병합/저장 ────────────────────────────────────────────────────────────────
def _merge_and_save(category_slug: str, docs, vectorstore: Optional[FAISS], cohort: Optional[str] = None):
    """
    새 인덱스를 기존 인덱스와 병합하고 저장.
    - 저장 위치: faiss_db/<category_slug>[/<cohort>]/
    - 문서 jsonl: docs/<category_slug>[/<cohort>]/doc.jsonl
    - 백업: backup/<category_slug>[/<cohort>]/<timestamp>/
    """
    faiss_dir = FAISS_BASE / category_slug / cohort if cohort else FAISS_BASE / category_slug
    faiss_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    index_faiss = faiss_dir / "index.faiss"
    index_pkl   = faiss_dir / "index.pkl"

    if index_faiss.exists() and index_pkl.exists():
        print("기존 인덱스 발견 → 병합 후 백업")
        emb = OpenAIEmbeddings(model="text-embedding-3-large")
        past_vs = FAISS.load_local(str(faiss_dir), embeddings=emb, allow_dangerous_deserialization=True)
        if vectorstore is None:
            vectorstore = past_vs
        else:
            vectorstore.merge_from(past_vs)

        bdir = BACKUP_BASE / category_slug / (cohort if cohort else "all") / ts
        bdir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(index_faiss), str(bdir / "index.faiss"))
        shutil.move(str(index_pkl),   str(bdir / "index.pkl"))

    if vectorstore is None:
        print("저장할 벡터스토어가 없습니다. 저장을 건너뜁니다.")
        return

    vectorstore.save_local(str(faiss_dir))
    print(f"저장 완료: {faiss_dir}")

    # 문서 메타 저장
    docs_dir = DOCS_BASE / category_slug / cohort if cohort else DOCS_BASE / category_slug
    docs_dir.mkdir(parents=True, exist_ok=True)
    doc_jsonl = docs_dir / "doc.jsonl"
    merged_docs = list(docs)

    if doc_jsonl.exists():
        past_docs = load_docs_from_jsonl(str(doc_jsonl))
        merged_docs.extend(past_docs)
        bdir = BACKUP_BASE / category_slug / (cohort if cohort else "all") / ts
        bdir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(doc_jsonl), str(bdir / "doc.jsonl"))

    save_docs_to_jsonl(merged_docs, str(doc_jsonl))
    print(f"문서 메타 저장: {doc_jsonl}")

# ── CLI ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    mx = parser.add_mutually_exclusive_group(required=True)
    mx.add_argument("--category", choices=list(CATEGORIES.keys()), help="단일 카테고리만 구축")
    mx.add_argument("--all", action="store_true", help="4개 카테고리를 일괄 구축")
    parser.add_argument("--cohort", help="입학년도(예: 2020). undergrad_rules/grad_rules에서만 사용")
    args = parser.parse_args()

    targets = list(CATEGORIES.keys()) if args.all else [args.category]

    for slug in targets:
        # undergrad_rules / grad_rules에서만 cohort 적용
        apply_cohort = args.cohort if slug in {"undergrad_rules", "grad_rules"} else None
        if args.cohort and apply_cohort is None:
            print(f"⚠️  '{slug}' 범주에서는 --cohort 옵션이 무시됩니다.")

        print("=" * 80)
        label = f"{CATEGORIES[slug]} | {slug}" + (f" | cohort={apply_cohort}" if apply_cohort else "")
        print(f"[{label}] 인덱스 구축 시작")

        docs, vs = _process_category(slug, cohort=apply_cohort)
        _merge_and_save(slug, docs, vs, cohort=apply_cohort)

    print("=" * 80)
    print("모든 작업 완료.")

if __name__ == "__main__":
    main()
