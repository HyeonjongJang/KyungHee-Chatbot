# admin_page.py
# Minimal Q/A admin with Private GitHub fetch support
# Sidebar = 날짜 범위 / ID 포함 / 정렬 / 페이지 크기

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import subprocess
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import streamlit as st

try:
    import pandas as pd
except Exception:
    pd = None

KST = ZoneInfo("Asia/Seoul")

# ─────────────────────────────────────────────────────────────────────────────
# Config (paths & secrets)
# ─────────────────────────────────────────────────────────────────────────────
JSON_PATH_DEFAULT = "./langsmith_runs.json"
JSON_PATH = st.secrets.get("json_path", JSON_PATH_DEFAULT)

GH_PAT = st.secrets.get("gh_pat")  # Fine-grained token
GH_REPO = st.secrets.get("private_repo")  # e.g. "khu-aimslab/secret-logs"
GH_PATH = st.secrets.get("private_path")  # e.g. "shrink_langsmith_json.json"
GH_REF = st.secrets.get("private_ref", "")  # optional branch/tag/commit

# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────
def _is_admin_logged_in() -> bool:
    return bool(st.session_state.get("is_admin", False))

def _logout():
    for k in ["is_admin", "admin_id", "_qa_page", "_last_json_mtime"]:
        st.session_state.pop(k, None)
    st.rerun()

def _admin_login_ui():
    st.title("Kyung Hee Regulations • Admin (Q/A)")
    with st.form("admin_login_form", clear_on_submit=False):
        admin_id = st.text_input("Admin ID")
        admin_key = st.text_input("Admin Key", type="password")
        submitted = st.form_submit_button("Log in")
        if submitted:
            valid_ids = set(st.secrets.get("admin_ids", []))
            valid_key = str(st.secrets.get("ADMIN_KEY", ""))
            if admin_id in valid_ids and admin_key == valid_key:
                st.session_state["is_admin"] = True
                st.session_state["admin_id"] = admin_id
                st.rerun()
            else:
                st.error("Invalid credentials.")

def _topbar(source_label: str):
    left, mid, right = st.columns([3, 2, 1])
    with left:
        st.subheader("Q/A Viewer · Admin")
        st.caption(source_label)
    with mid:
        if st.button("🔄 Refresh (ignore cache)"):
            _fetch_private_json.clear()
            _load_local_items.clear()
            st.rerun()
    with right:
        st.button("Log out", on_click=_logout)

# ─────────────────────────────────────────────────────────────────────────────
# Utils
# ─────────────────────────────────────────────────────────────────────────────
def _safe_parse_dt(x: Any) -> Optional[datetime]:
    if not x:
        return None
    s = str(x).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None
    
def _basename_like(s: Any) -> str:
    """
    경로/URL/문자열에서 파일명 유사 부분만 추출.
    예: 'https://foo/bar/baz.pdf?p=3' -> 'baz.pdf'
    """
    if not s:
        return ""
    try:
        t = str(s).strip().strip('"').strip("'")
        # 쿼리스트립
        t = t.split("?", 1)[0].split("#", 1)[0]
        # 경로 베이스네임
        t = t.split("/")[-1].split("\\")[-1]
        return t
    except Exception:
        return str(s)
    
def _format_contexts(ctxs: Any, max_items: int = 5) -> str:
    """[{filename, page, snippet}] 리스트를 표출용 문자열로."""
    if not isinstance(ctxs, list) or not ctxs:
        return ""
    parts = []
    for c in ctxs[:max_items]:
        try:
            fn = (c.get("filename") or "").strip()
            pg = str(c.get("page") or "").strip()
            sn = (c.get("snippet") or "").strip()
            head = fn if fn else "문서"
            if pg:
                head += f" (p.{pg})"
            parts.append(f"• {head}: {sn}")
        except Exception:
            continue
    return "\n".join(parts)

def _extract_contexts_from_outputs(run: Dict[str, Any], topk: int = 5) -> List[Dict[str, Any]]:
    outs = _as_dict(run.get("outputs"))
    out = []
    def harvest(seq):
        for d in (seq or []):
            try:
                if isinstance(d, dict):
                    meta = _as_dict(d.get("metadata"))
                    fname = meta.get("filename") or _basename_like(meta.get("source"))
                    page  = meta.get("page") or meta.get("page_number") or ""
                    text  = d.get("page_content") or d.get("content") or ""
                else:
                    fname, page, text = "", "", str(d)
                if text:
                    out.append({"filename": (fname or ""), "page": page, "snippet": text})
            except Exception:
                continue
    for k in ("context", "documents", "source_documents"):
        v = outs.get(k)
        if isinstance(v, list) and v:
            harvest(v)
    # dedup & topk
    seen, uniq = set(), []
    for x in out:
        key = (x.get("filename",""), x.get("page",""), x.get("snippet","")[:120])
        if key in seen: 
            continue
        seen.add(key); uniq.append(x)
    return uniq[:topk]

def _to_rows_from_runs(reps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for r in reps:
        ts = _safe_parse_dt(r.get("start_time")) or _safe_parse_dt(r.get("end_time"))
        if ts:
            ts = ts.astimezone(KST)
        sid = _extract_member_id(r)
        q = _normalize_text(_extract_question(r))
        a = _strip_source_lines(_extract_answer(r))

        # 🔹 추가: outputs에서 참고문서 뽑기
        ctxs = _extract_contexts_from_outputs(r, topk=5)
        ctx_str = _format_contexts(ctxs, max_items=5)

        rows.append({
            "ts": ts,
            "시각(KST)": ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "",
            "ID": sid,
            "질문": _clip(q, 500),
            "답변": _clip(a, 800),
            "참고문서": ctx_str,      # 표 표시
            "_q_full": q,
            "_a_full": a,
            "_contexts": ctxs,        # 다운로드용
        })
    ...


def _as_dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}

def _dig(d: Dict[str, Any], *keys) -> Any:
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur

def _clip(s: Any, n: int) -> str:
    try:
        if isinstance(s, str):
            t = s
        elif isinstance(s, (dict, list)):
            t = json.dumps(s, ensure_ascii=False)
        else:
            t = str(s)
    except Exception:
        t = str(s)
    return (t[: n - 1] + "…") if len(t) > n else t

def _normalize_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def _strip_source_lines(ans: str) -> str:
    if not isinstance(ans, str):
        return ans
    lines = [ln for ln in ans.splitlines() if not re.match(r"^\s*Source\s*:?", ln, flags=re.I)]
    return "\n".join(lines).strip()

def _answers_like_source_only(ans: str) -> bool:
    if not isinstance(ans, str) or not ans.strip():
        return True
    return bool(re.match(r"^\s*Source\s*:?", ans.strip(), flags=re.I))

def _get_depth(run: Dict[str, Any]) -> int:
    md = _dig(run, "extra", "metadata") or {}
    try:
        return int(md.get("ls_run_depth", 999))
    except Exception:
        return 999

# ─────────────────────────────────────────────────────────────────────────────
# Private GitHub fetch (cached)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _fetch_private_json(pat: str, repo: str, path: str, ref: str = "") -> List[Any]:
    """
    Shallow-clone a private repo and load JSON/JSONL file.
    """
    with tempfile.TemporaryDirectory() as td:
        url = f"https://{pat}@github.com/{repo}.git"
        cmd = ["git", "clone", "--depth", "1"]
        if ref:
            cmd += ["--branch", ref]
        cmd += [url, td]
        subprocess.check_call(cmd)
        fpath = os.path.join(td, path)
        if not os.path.isfile(fpath):
            raise FileNotFoundError(f"File not found in repo: {path}")

        # Read JSON or JSONL
        with open(fpath, "r", encoding="utf-8") as f:
            txt = f.read()
        try:
            data: Any = json.loads(txt)
        except json.JSONDecodeError:
            data = [json.loads(line) for line in txt.splitlines() if line.strip()]
        if isinstance(data, dict):
            data = data.get("runs") or data.get("data") or data.get("items") or []
        if not isinstance(data, list):
            data = []
        return data

# ─────────────────────────────────────────────────────────────────────────────
# Local load (cached)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load_local_items(path: str) -> List[Any]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    try:
        data: Any = json.loads(txt)  # JSON array or dict
    except json.JSONDecodeError:
        data = [json.loads(line) for line in txt.splitlines() if line.strip()]
    if isinstance(data, dict):
        data = data.get("runs") or data.get("data") or []
    if not isinstance(data, list):
        data = []
    return data

# ─────────────────────────────────────────────────────────────────────────────
# Q/A extractors (for full LangSmith runs)
# ─────────────────────────────────────────────────────────────────────────────
def _extract_member_id(run: Dict[str, Any]) -> str:
    v = _dig(run, "inputs", "student_id")
    if isinstance(v, (str, int)):
        return str(v)
    v = _dig(run, "extra", "metadata", "student_id")
    if v:
        return str(v)
    inp = _as_dict(run.get("inputs"))
    for k in ["member_id", "user_id", "id", "student"]:
        if k in inp and inp[k]:
            return str(inp[k])
    for t in run.get("tags") or []:
        if isinstance(t, str) and ":" in t:
            k, val = t.split(":", 1)
            if k.lower() in {"user", "member", "student", "student_id"} and val.strip():
                return val.strip()
    return run.get("session_id") or ""

def _extract_messages_from_llm(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    msgs = _dig(run, "inputs", "messages")
    if isinstance(msgs, list) and msgs and isinstance(msgs[0], list):
        msgs = msgs[0]  # nested list 방어
    out: List[Dict[str, Any]] = []
    if isinstance(msgs, list):
        for m in msgs:
            if not isinstance(m, dict):
                out.append({"role": "unknown", "content": _clip(m, 400)})
                continue
            role = m.get("role")
            content = m.get("content")
            if role and content:
                out.append({"role": role, "content": content})
                continue
            kw = _as_dict(m.get("kwargs"))
            ct = kw.get("content")
            tp = (kw.get("type") or "").lower()
            if ct:
                role = "user" if tp in {"human", "user"} else "assistant" if tp in {"ai", "assistant"} else tp or "unknown"
                out.append({"role": role, "content": ct})
                continue
            out.append({"role": "unknown", "content": _clip(m, 400)})
    return out

def _extract_question(run: Dict[str, Any]) -> str:
    v = _dig(run, "inputs", "input")
    if isinstance(v, str) and v.strip():
        return v
    msgs = _extract_messages_from_llm(run)
    for m in reversed(msgs):
        if (m.get("role") or "").lower() in {"user", "human"} and m.get("content"):
            return str(m["content"])
    for k in ["question", "query", "prompt"]:
        v = _dig(run, "inputs", k)
        if isinstance(v, str) and v.strip():
            return v
    return ""

def _extract_answer(run: Dict[str, Any]) -> str:
    v = _dig(run, "outputs", "answer")
    if isinstance(v, str) and v.strip():
        return v
    out = run.get("outputs")
    if isinstance(out, str) and out.strip():
        return out
    if isinstance(out, dict):
        gen = _dig(out, "generations", 0, 0, "text")
        if isinstance(gen, str) and gen.strip():
            return gen
        content = out.get("content")
        if isinstance(content, str) and content.strip():
            return content
        outp = out.get("output")
        if isinstance(outp, str) and outp.strip():
            return outp
    return ""

def _score_for_qa(run: Dict[str, Any]) -> Tuple:
    rt = (run.get("run_type") or "").lower()
    depth = _get_depth(run)
    has_q = bool(_extract_question(run))
    ans = _extract_answer(run)
    has_ans = bool(ans)
    bad_ans = _answers_like_source_only(ans)
    end = _safe_parse_dt(run.get("end_time")) or _safe_parse_dt(run.get("start_time")) or datetime.min.replace(tzinfo=timezone.utc)
    return (100 if rt == "chain" else 0, -depth, 20 if has_q else 0, 40 if has_ans else 0, -30 if bad_ans else 0, end.timestamp())

def _select_representative_runs(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_trace: Dict[str, List[Dict[str, Any]]] = {}
    for r in runs:
        by_trace.setdefault(r.get("trace_id") or "", []).append(r)
    selected: List[Dict[str, Any]] = []
    for _, group in by_trace.items():
        best = max(group, key=_score_for_qa)
        selected.append(best)
    return selected

# ─────────────────────────────────────────────────────────────────────────────
# Q/A rows coercion (handles minimal JSON as well)
# ─────────────────────────────────────────────────────────────────────────────
def _coerce_to_rows(items: List[Any]) -> List[Dict[str, Any]]:
    if items and isinstance(items, list) and isinstance(items[0], dict) and (
        "question" in items[0] and "answer" in items[0]
    ):
        rows: List[Dict[str, Any]] = []
        for x in items:
            ts = _safe_parse_dt(x.get("ts") or x.get("timestamp") or x.get("time"))
            if ts:
                ts = ts.astimezone(KST)
            q = _normalize_text(str(x.get("question", "")))
            a = _strip_source_lines(str(x.get("answer", "")))
            rid = str(x.get("id", "")) if x.get("id") is not None else ""

            # 🔹 여기 추가: contexts 표시용
            ctxs = x.get("contexts") or []
            ctx_str = _format_contexts(ctxs, max_items=5)

            rows.append({
                "ts": ts,
                "시각(KST)": ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "",
                "ID": rid,
                "질문": _clip(q, 500),
                "답변": _clip(a, 800),
                "참고문서": ctx_str,     # 👈 표에 보일 컬럼
                "_q_full": q,
                "_a_full": a,
                "_contexts": ctxs,       # 👈 다운로드용 원본
            })
        return rows
    # Fallback: full runs
    reps = _select_representative_runs([r for r in items if isinstance(r, dict)])
    return _to_rows_from_runs(reps)

# ─────────────────────────────────────────────────────────────────────────────
# Page
# ─────────────────────────────────────────────────────────────────────────────
def admin_page():
    if not _is_admin_logged_in():
        _admin_login_ui()
        return

    # Decide source: Private repo if all secrets exist; else local file
    use_gh = bool(GH_PAT and GH_REPO and GH_PATH)
    items: List[Any] = []
    source_label = ""

    try:
        if use_gh:
            items = _fetch_private_json(GH_PAT, GH_REPO, GH_PATH, GH_REF)
            ref_part = f"@{GH_REF}" if GH_REF else ""
            source_label = f"Source: Private GitHub · {GH_REPO}/{GH_PATH}{ref_part}"
        else:
            items = _load_local_items(JSON_PATH)
            source_label = f"Source: Local JSON · {JSON_PATH}"
    except Exception as e:
        st.error(f"Data load failed. Check secrets/paths. ({e})")
        return

    rows = _coerce_to_rows(items)
    if not rows:
        _topbar(source_label)
        st.info("No Q/A records found.")
        return

    _topbar(source_label)

    # ── Sidebar: 필요한 4가지만 ────────────────────────────────────────────
    st.sidebar.markdown("### 필터")
    dates = [r["ts"].date() for r in rows if r["ts"]]
    if dates:
        dmin, dmax = min(dates), max(dates)
    else:
        today = date.today()
        dmin = dmax = today
    d1, d2 = st.sidebar.date_input("날짜 범위", value=(dmin, dmax), min_value=dmin, max_value=dmax)

    id_kw = st.sidebar.text_input("ID 포함", value="")

    sort_opt = st.sidebar.selectbox("정렬", ["날짜/시간 오름차순", "날짜/시간 내림차순"], index=1)

    page_size = st.sidebar.number_input("페이지 크기", min_value=10, max_value=200, value=50, step=10)

    # ── Filter & sort ───────────────────────────────────────────────────────
    def _ok(r):
        t = r["ts"]
        if t and (t.date() < d1 or t.date() > d2):
            return False
        if id_kw and id_kw.lower() not in (r["ID"] or "").lower():
            return False
        return True

    filtered = [r for r in rows if _ok(r)]
    reverse = sort_opt.endswith("내림차순")
    filtered.sort(key=lambda r: r["ts"] or datetime.min, reverse=reverse)

    # Pagination
    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    if "_qa_page" not in st.session_state:
        st.session_state["_qa_page"] = 1
    page = max(1, min(st.session_state["_qa_page"], total_pages))
    start = (page - 1) * page_size
    end = min(start + page_size, total)
    page_rows = filtered[start:end]

    st.markdown(f"**Results:** {total:,}  ·  Showing {start+1}-{end}  ·  Page {page}/{total_pages}")

    view_cols = ["시각(KST)", "ID", "질문", "답변", "참고문서"]
    if pd is not None:
        df = pd.DataFrame([{k: r[k] for k in view_cols} for r in page_rows])
        st.dataframe(
            df, use_container_width=True, hide_index=True,
            column_config={"참고문서": st.column_config.TextColumn(width="large")}
        )
    else:
        st.table([{k: r[k] for k in view_cols} for r in page_rows])

    # 페이지 이동 버튼
    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        if st.button("◀ 이전", disabled=(page <= 1), key="qa_prev"):
            st.session_state["_qa_page"] = max(1, page - 1)
            st.rerun()
    with c3:
        if st.button("다음 ▶", disabled=(page >= total_pages), key="qa_next"):
            st.session_state["_qa_page"] = min(total_pages, page + 1)
            st.rerun()

    # 다운로드(필터 적용본)
    colA, colB = st.columns(2)
    with colA:
        if pd is not None:
            fdf = pd.DataFrame([{k: r[k] for k in view_cols} for r in filtered])
            csv_bytes = fdf.to_csv(index=False).encode("utf-8-sig")
        else:
            import csv as _csv, io as _io
            sio = _io.StringIO()
            writer = _csv.DictWriter(sio, fieldnames=view_cols)
            writer.writeheader()
            for r in filtered:
                writer.writerow({k: r[k] for k in view_cols})
            csv_bytes = sio.getvalue().encode("utf-8-sig")
        st.download_button("⬇️ CSV (filtered)", csv_bytes, file_name="qa_filtered.csv", mime="text/csv")
    with colB:
        payload = [
    {
        "timestamp_kst": r["시각(KST)"],
        "id": r["ID"],
        "question": r["_q_full"],
        "answer": r["_a_full"],
        "contexts": r.get("_contexts", [])  # 👈 추가
    }
            for r in filtered
        ]
        jb = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        st.download_button("⬇️ JSON (filtered)", jb.getvalue(), file_name="qa_filtered.json", mime="application/json")

# Standalone
if __name__ == "__main__":
    try:
        st.set_page_config(page_title="KHU Admin – Q/A Viewer", layout="wide")
    except Exception:
        pass
    admin_page()
