# add_document.py  — JSON 청크(.json/.jsonl) + 코호트 대응, 백업/병합 일관화
# Phase 1: 메타데이터 표준화(URI/스키마/정규화) + HTTP URI/소스/MD5 보강 버전

import os, re, shutil, argparse, datetime, math, json, hashlib
from pathlib import Path
from typing import List, Tuple, Optional, Iterable, Union

from dotenv import load_dotenv
from langchain_community.document_loaders import PDFMinerLoader, NotebookLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS

# LangChain Document 호환 (langchain==0.3 계열)
try:
    from langchain.schema import Document as LCDocument
except Exception:
    from langchain_core.documents import Document as LCDocument  # fallback

from utils import load_docs_from_jsonl, save_docs_to_jsonl

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: metadata schema & URI helpers
# ─────────────────────────────────────────────────────────────────────────────
SCHEMA_VERSION = "1.0"

PROGRAM_SET = {
    "UG", "MS", "PHD", "IME_MS", "IME_PHD",  # 필요시 확장
}

HTTP_URI_BASE = "https://kg.khu.ac.kr/reg"  # 영구 URI 네임스페이스(운영 시 고정 권장)

def _norm_program(v: str | None) -> str | None:
    if not v:
        return None
    x = str(v).strip().upper().replace("-", "_")
    return x if x in PROGRAM_SET else None

def _norm_cohort(v: str | None) -> str | None:
    # "2023" → "Cohort_2023"
    if not v:
        return None
    s = "".join(ch for ch in str(v) if ch.isdigit())
    if len(s) == 4 and s.startswith("20"):
        return f"Cohort_{s}"
    return None

def _parse_article_clause(md: dict) -> tuple[int | None, int | None]:
    """
    JSON 메타에 article_number / articleNumber / "제N조" 형태가 섞여 있어도 흡수.
    clause는 없으면 None
    """
    def _to_int(x):
        try:
            return int(x)
        except Exception:
            return None

    a = md.get("articleNumber") or md.get("article_number") or md.get("articleNo") or md.get("article")
    if isinstance(a, str):
        # "제15조" → 15
        m = re.search(r"(\d+)", a)
        a = m.group(1) if m else a
    a = _to_int(a)

    c = md.get("clauseNumber") or md.get("clause_no") or md.get("clause")
    if isinstance(c, str):
        m = re.search(r"(\d+)", c)
        c = m.group(1) if m else c
    c = _to_int(c)

    return a, c

def _infer_content_type(md: dict, page_content: str) -> str:
    # JSON에서 "content_type: table"이면 table, 아니면 text 기본
    ct = (md.get("content_type") or md.get("contentType") or "").strip().lower()
    if ct == "table":
        return "table"
    # 간단 휴리스틱: 파이프(|) 테이블 감지 → table
    if page_content and page_content.count("|") >= 4 and "\n| ---" in page_content:
        return "table"
    return "text"

def _build_http_uris(code: str, vdate: str, art: int | None, cl: int | None) -> tuple[str | None, str | None]:
    """
    영구 HTTP URI 생성.
    예: https://kg.khu.ac.kr/reg/AA-2024-09-01#art15 / #art15-cl2
    """
    if not (code and vdate and art is not None):
        return None, None
    base = f"{HTTP_URI_BASE}/{code}-{vdate}"
    article_uri = f"{base}#art{art}"
    clause_uri = f"{article_uri}-cl{cl}" if cl is not None else None
    return article_uri, clause_uri

def _compute_md5_from_text(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()

def _attach_uri_and_schema(meta: dict, page_content: str) -> dict:
    m = dict(meta or {})

    # 0) 소스/재현성 정보
    # filename -> sourceFile (표준 메타명 고정)
    if m.get("sourceFile") is None:
        m["sourceFile"] = m.get("filename") or None
    # md5 (페이지/본문 텍스트 기준, 재현 가능한 지문)
    m["md5"] = _compute_md5_from_text(page_content)

    # 1) 기본 스키마 라인업
    m.setdefault("schema_version", SCHEMA_VERSION)
    m.setdefault("documentCode", (m.get("document_code") or m.get("code") or "").strip())
    m.setdefault("versionDate", (m.get("versionDate") or m.get("version_date") or "").strip() or None)
    # 선택적 기간
    ef = m.get("effectiveFrom") or m.get("effective_from") or None
    eu = m.get("effectiveUntil") or m.get("effective_until") or None
    m["effectiveFrom"] = ef or None
    m["effectiveUntil"] = eu or None

    # 2) 페이지 정규화
    page = m.get("page") or m.get("page_number") or m.get("pageNumber")
    if page is not None:
        try:
            m["page"] = int(page)
        except Exception:
            m["page"] = page
    # (선택) 레거시 키 삭제는 유지 보수상 주석 처리

    # 3) 정규형 program/cohort
    m["program"] = _norm_program(m.get("program"))
    m["cohort"]  = _norm_cohort(m.get("cohort") or m.get("year") or m.get("student_year"))

    # 4) contentType
    m["contentType"] = _infer_content_type(m, page_content)

    # 5) article/clause 정규화
    a, c = _parse_article_clause(m)
    if a is not None:
        m["articleNumber"] = a
    if c is not None:
        m["clauseNumber"] = c
    else:
        m.setdefault("clauseNumber", None)

    # 6) 관계 후보 필드 존재 보장
    for k in ("overrides", "cites", "hasExceptionFor"):
        if k not in m or m[k] is None:
            m[k] = []

    # 7) 식별자: URN + HTTP 영구 URI 동시 부여
    code = (m.get("documentCode") or "").strip()
    vdate = (m.get("versionDate") or "").strip()
    art = m.get("articleNumber")
    cl  = m.get("clauseNumber")

    # 7-a) URN (기존 방식 유지)
    if code and vdate and (art is not None):
        cl_suffix = f":cl{cl}" if (cl is not None) else ""
        m["uri"] = f"urn:khu:reg:{code}:{vdate}:art{art}{cl_suffix}"
    else:
        m.setdefault("uri", None)

    # 7-b) HTTP URI (체크리스트 요구)
    article_http, clause_http = _build_http_uris(code, vdate, art, cl)
    # 둘 다 None일 수 있으니 키는 반드시 존재하도록 보장
    m["articleUri"] = article_http
    m["clauseUri"]  = clause_http

    return m

# ─────────────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────────────
CATEGORIES = {
    "regulations":       "규정",
    "undergrad_rules":   "학부 시행세칙",
    "grad_rules":        "대학원 시행세칙",
    "academic_system":   "학사제도",
}

BASE         = Path(".")
FAISS_BASE   = BASE / "faiss_db"
TODO_BASE    = BASE / "todo_documents"
PAST_BASE    = BASE / "past_documents"
DOCS_BASE    = BASE / "docs"
BACKUP_BASE  = BASE / "backup"

SUPPORTED_EXTS = {".pdf", ".txt", ".ipynb", ".json", ".jsonl"}

# ─────────────────────────────────────────────────────────────────────────────
# 로더들
# ─────────────────────────────────────────────────────────────────────────────
def _norm_spaces(s: str) -> str:
    s = s.replace("\x0c", " ").replace("\n", " ")
    return re.sub(r"\s{2,}", " ", s).strip()

def _make_source_prefix(filename: str) -> str:
    """UI의 Source 처리 규약에 맞게 접두사 구성"""
    name = (filename or "").strip()
    return f"Source : {name}\n" if name else ""

def _as_document(page_content: str, metadata: Optional[dict] = None) -> LCDocument:
    return LCDocument(page_content=page_content, metadata=metadata or {})

def _load_pdf_txt_ipynb(path: Path) -> List[LCDocument]:
    """기존 파이프라인: pdf/txt/ipynb → 청크 분할"""
    if path.suffix.lower() == ".txt":
        docs = TextLoader(str(path)).load()
    elif path.suffix.lower() == ".pdf":
        docs = PDFMinerLoader(str(path)).load()
        for d in docs:
            d.page_content = _norm_spaces(d.page_content)
    elif path.suffix.lower() == ".ipynb":
        docs = NotebookLoader(str(path), include_outputs=False, remove_newline=True).load()
    else:
        return []

    splitter = RecursiveCharacterTextSplitter(chunk_size=2048, chunk_overlap=256)
    splits = splitter.split_documents(docs)

    # 파일명 메타 + Source 접두사 부착 + Phase1 메타 보강
    for d in splits:
        meta = dict(d.metadata or {})
        meta["filename"] = path.name
        meta["category"] = meta.get("category", "")
        d.page_content = _make_source_prefix(path.name) + (d.page_content or "")

        # ▼▼ Phase 1: 메타 보강(URI/스키마/정규화)
        meta = _attach_uri_and_schema(meta, d.page_content)

        d.metadata = meta
    return splits

def _load_json_chunk(path: Path) -> List[LCDocument]:
    """
    process_pdf.py / upgrade_tables.py 가 생성한 JSON 청크 지원.
    기대 형식:
      { "text": "...", "metadata": { "document_title": "...", "page_number": 1, ... } }
    또는 JSON 배열/JSONL 유사 구조도 최대한 수용.
    """
    def _coerce_one(obj: dict, default_fname: str) -> Optional[LCDocument]:
        if not isinstance(obj, dict):
            return None
        text = obj.get("text") or obj.get("page_content") or ""
        md   = obj.get("metadata") or obj.get("meta") or {}
        if not isinstance(md, dict):
            md = {}

        # 파일명 결정: document_title > filename > JSON 파일명
        doc_title = (md.get("document_title") or "").strip()
        # UI에서 '원문 다운로드'가 PDF 기준으로 작동하므로 .pdf 확장자를 붙여준다.
        # (로컬에 실제 PDF가 존재하면 second_page에서 찾아 다운로드 제공)
        filename  = md.get("filename") or (doc_title + ".pdf" if doc_title else default_fname)

        # 접두사 + 본문 정리
        page_content = _make_source_prefix(filename) + _norm_spaces(str(text))

        # 메타 보강
        meta = dict(md)
        meta["filename"] = filename
        # ▼▼ Phase 1: 메타 보강(URI/스키마/정규화 + HTTP URI/소스/MD5)
        meta = _attach_uri_and_schema(meta, page_content)

        return _as_document(page_content, meta)

    docs: List[LCDocument] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except Exception:
        return docs

    # 1) JSONL 라이크?
    if "\n" in raw and not raw.lstrip().startswith(("{", "[")):
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                d = _coerce_one(obj, default_fname=path.name)
                if d: docs.append(d)
            except Exception:
                continue
        return docs

    # 2) JSON (object or array)
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        return docs

    if isinstance(data, dict) and ("text" in data or "page_content" in data):
        d = _coerce_one(data, default_fname=path.name)
        if d: docs.append(d)
        return docs

    if isinstance(data, list):
        for obj in data:
            d = _coerce_one(obj, default_fname=path.name)
            if d: docs.append(d)
    return docs

def _load_path_as_documents(path: Path) -> List[LCDocument]:
    ext = path.suffix.lower()
    if ext in {".pdf", ".txt", ".ipynb"}:
        return _load_pdf_txt_ipynb(path)
    if ext in {".json", ".jsonl"}:
        return _load_json_chunk(path)
    return []

# ─────────────────────────────────────────────────────────────────────────────
# 수집/임베딩
# ─────────────────────────────────────────────────────────────────────────────
def _gather_files(todo_dir: Path) -> List[Path]:
    if not todo_dir.exists():
        return []
    return [p for p in todo_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]

def _build_index_in_batches(splits: List[LCDocument], emb, docs_per_batch: int = 32) -> Optional[FAISS]:
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

def _process_category(category_slug: str, cohort: Optional[str] = None) -> Tuple[List[LCDocument], Optional[FAISS]]:
    """
    todo_documents/<category_slug>[/<cohort>] 아래의 파일들을 읽어
    (.pdf/.txt/.ipynb/.json/.jsonl) → Document 목록 생성 → 임베딩/FAISS 구성
    """
    emb = OpenAIEmbeddings(model="text-embedding-3-large")

    todo_dir = TODO_BASE / category_slug / cohort if cohort else TODO_BASE / category_slug
    past_dir = PAST_BASE / category_slug / cohort if cohort else PAST_BASE / category_slug
    past_dir.mkdir(parents=True, exist_ok=True)

    files = _gather_files(todo_dir)
    if not files:
        label = f"{CATEGORIES[category_slug]} | {category_slug}" + (f" | cohort={cohort}" if cohort else "")
        print(f"[{label}] 처리할 파일이 없습니다: {todo_dir}")
        return [], None

    all_splits: List[LCDocument] = []
    for i, f in enumerate(sorted(files), 1):
        print(f"[{i}/{len(files)}] 로딩/분할: {f.relative_to(todo_dir)}")
        try:
            docs = _load_path_as_documents(f)
            # 공통 메타 부여(카테고리/코호트) + Phase1 보강 재적용(코호트 정규화 목적)
            for d in docs:
                meta = dict(d.metadata or {})
                meta["category"] = category_slug
                if cohort:
                    meta["cohort"] = cohort
                # ▼▼ Phase 1: 코호트 주입 후 재보정(정규화/URI 보강 + HTTP URI/소스/MD5)
                meta = _attach_uri_and_schema(meta, d.page_content)
                d.metadata = meta
            if docs:
                print(f"   → 청크 수: {len(docs)}")
                all_splits.extend(docs)
            else:
                print("   → 건너뜀(로더가 문서를 만들지 못함)")
        finally:
            # 원본은 past_documents로 이동(운영상 중복 임베딩 방지)
            try:
                shutil.move(str(f), str(past_dir / f.name))
            except Exception as e:
                print(f"   → 이동 실패: {e}")

    if not all_splits:
        print(f"[{CATEGORIES[category_slug]}] 생성된 청크가 없습니다. 인덱스를 저장하지 않습니다.")
        return [], None

    vs_new = _build_index_in_batches(all_splits, emb, docs_per_batch=32)
    return all_splits, vs_new

# ─────────────────────────────────────────────────────────────────────────────
# 병합/저장
# ─────────────────────────────────────────────────────────────────────────────
def _merge_and_save(category_slug: str, docs: List[LCDocument], vectorstore: Optional[FAISS], cohort: Optional[str] = None):
    """
    - 저장: faiss_db/<category>[/<cohort>]/{index.faiss,index.pkl}
    - 문서 메타: docs/<category>[/<cohort>]/doc.jsonl (기존과 합쳐 백업)
    - 백업: backup/<category>[/<cohort or all>]/<timestamp>/
    """
    faiss_dir = FAISS_BASE / category_slug / cohort if cohort else FAISS_BASE / category_slug
    faiss_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    index_faiss = faiss_dir / "index.faiss"
    index_pkl   = faiss_dir / "index.pkl"

    # 기존 인덱스가 있으면 병합 후 백업
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

    # 문서 메타 저장(JSONL) — 기존과 합쳐 백업
    docs_dir = DOCS_BASE / category_slug / cohort if cohort else DOCS_BASE / category_slug
    docs_dir.mkdir(parents=True, exist_ok=True)
    doc_jsonl = docs_dir / "doc.jsonl"

    merged_docs: List[LCDocument] = list(docs)
    if doc_jsonl.exists():
        past_docs = load_docs_from_jsonl(str(doc_jsonl))
        merged_docs.extend(past_docs)
        bdir = BACKUP_BASE / category_slug / (cohort if cohort else "all") / ts
        bdir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(doc_jsonl), str(bdir / "doc.jsonl"))

    save_docs_to_jsonl(merged_docs, str(doc_jsonl))
    print(f"문서 메타 저장: {doc_jsonl}")

# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    mx = parser.add_mutually_exclusive_group(required=True)
    mx.add_argument("--category", choices=list(CATEGORIES.keys()), help="단일 카테고리 구축")
    mx.add_argument("--all", action="store_true", help="4개 카테고리를 일괄 구축")
    parser.add_argument("--cohort", help="입학년도(예: 2020). undergrad_rules/grad_rules에서만 사용")
    args = parser.parse_args()

    targets = list(CATEGORIES.keys()) if args.all else [args.category]

    for slug in targets:
        # cohort는 학부/대학원 시행세칙에서만 의미 있음
        apply_cohort = args.cohort if slug in {"undergrad_rules", "grad_rules"} else None
        if args.cohort and apply_cohort is None:
            print(f"⚠️ '{slug}' 범주에서는 --cohort 옵션이 무시됩니다.")

        print("=" * 80)
        label = f"{CATEGORIES[slug]} | {slug}" + (f" | cohort={apply_cohort}" if apply_cohort else "")
        print(f"[{label}] 인덱스 구축 시작")

        docs, vs = _process_category(slug, cohort=apply_cohort)
        _merge_and_save(slug, docs, vs, cohort=apply_cohort)

    print("=" * 80)
    print("모든 작업 완료.")

if __name__ == "__main__":
    main()
