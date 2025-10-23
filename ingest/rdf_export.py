#!/usr/bin/env python3
"""
rdf_export.py — RDF exporter for KyungHee-Chatbot

Features:
  1) HTTP URI 병행: URN과 HTTP URI가 모두 있을 경우 owl:sameAs로 동치 연결하고,
     기본 subject는 HTTP URI(있으면)를 사용합니다.
  2) 관계 샘플 주입 옵션(--inject-samples): 5~10개의 관계 트리플을
     안전한 EX 네임스페이스(https://kg.khu.ac.kr/example/) 하에 생성합니다.
     * 실제 데이터와 혼동 방지를 위해 기본은 OFF입니다.
  3) pyshacl.validate() 훅(--validate --shapes ontology/shapes.ttl):
     내보낸 그래프를 주어진 SHACL shapes로 검증합니다.
  4) 디버깅/브라우징 편의를 위한 메타 방출:
     RDFS.label / DCTERMS.source / UNI.page / UNI.md5
"""
from __future__ import annotations

import argparse
import json
import random
from typing import Dict, Iterable, Optional, Tuple

from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS, XSD, OWL, DCTERMS

# === Namespaces ===
UNI = Namespace("https://kg.khu.ac.kr/uni#")      # vocab (classes/properties)
ID  = Namespace("https://kg.khu.ac.kr/id/")       # instances (optional)
EX  = Namespace("https://kg.khu.ac.kr/example/")  # sample instance space

# ---------- helpers ----------
def _safe_uri(u: str) -> Optional[URIRef]:
    try:
        return URIRef(u)
    except Exception:
        return None

def _pick_subject_and_link(meta: Dict, g: Graph) -> URIRef:
    """
    Decide canonical subject and, if both URN and HTTP exist, add owl:sameAs links.
    Priority: clauseUri(http) > articleUri(http) > meta['uri'] (could be URN or http)
    """
    http = meta.get("clauseUri") or meta.get("articleUri")
    any_uri = meta.get("uri")

    if http:
        subj = URIRef(http)
        if any_uri and any_uri != http:
            u2 = _safe_uri(any_uri)
            if u2:
                g.add((URIRef(http), OWL.sameAs, u2))
                g.add((u2, OWL.sameAs, URIRef(http)))
    elif any_uri:
        subj = URIRef(any_uri)
    else:
        raise ValueError("meta lacks both 'uri' and 'articleUri/clauseUri'")
    return subj

# ---------- conversion ----------
def chunk_meta_to_rdf(meta: Dict) -> Tuple[Graph, URIRef]:
    """
    Convert one meta dict to RDF. Returns (graph, canonical_subject).
    """
    g = Graph()
    g.bind("uni", UNI)
    g.bind("id", ID)
    g.bind("owl", OWL)
    g.bind("ex", EX)

    # subject (and sameAs links)
    subj = _pick_subject_and_link(meta, g)

    # typing
    g.add((subj, RDF.type, UNI.Clause))

    # basic attributes
    if "category" in meta:
        g.add((subj, UNI.category, Literal(meta["category"])))
    if "program" in meta:
        g.add((subj, UNI.appliesToProgram, Literal(meta["program"])))
    if "cohort" in meta:
        g.add((subj, UNI.appliesToCohort, Literal(meta["cohort"])))
    if "article" in meta:
        # 숫자/문자 모두 허용—JSONL이 문자열일 수도 있으므로 Literal 그대로
        g.add((subj, UNI.article, Literal(meta["article"])))
    if "clause" in meta:
        g.add((subj, UNI.clause, Literal(meta["clause"])))

    # effective period
    if meta.get("effectiveFrom"):
        g.add((subj, UNI.effectiveFrom, Literal(meta["effectiveFrom"], datatype=XSD.date)))
    if meta.get("effectiveUntil"):
        g.add((subj, UNI.effectiveUntil, Literal(meta["effectiveUntil"], datatype=XSD.date)))

    # relations (as-is; tolerate bad URIs)
    for k, pred in (("overrides", UNI.overrides), ("cites", UNI.cites)):
        vals = meta.get(k) or []
        for u in vals:
            ur = _safe_uri(u) if isinstance(u, str) else None
            if ur:
                g.add((subj, pred, ur))

    # hasExceptionFor: URI or literal
    for exc in (meta.get("hasExceptionFor") or []):
        if isinstance(exc, str) and exc.startswith("http"):
            ur = _safe_uri(exc)
            if ur:
                g.add((subj, UNI.hasExceptionFor, ur))
        else:
            g.add((subj, UNI.hasExceptionFor, Literal(exc)))

    # ---- optional debugging metadata ----
    # label
    lbl = meta.get("label")
    if lbl:
        g.add((subj, RDFS.label, Literal(lbl)))
    # source
    src = meta.get("source")
    if src:
        g.add((subj, DCTERMS.source, Literal(src)))
    # page (int)
    if meta.get("page") is not None:
        try:
            g.add((subj, UNI.page, Literal(int(meta["page"]), datatype=XSD.integer)))
        except Exception:
            # 페이지가 숫자가 아니면 문자열로라도 남겨둠
            g.add((subj, UNI.page, Literal(str(meta["page"]))))
    # md5
    md5v = meta.get("md5")
    if md5v:
        g.add((subj, UNI.md5, Literal(md5v)))

    return g, subj

# ---------- sample relation injector ----------
_SAMPLE_RELATION_PROPS = [UNI.overrides, UNI.cites, UNI.hasExceptionFor]

def inject_sample_relations(g: Graph, subj: URIRef, count: int = 6, seed: Optional[int] = 42) -> None:
    """
    Inject 5~10 demo relation triples under EX namespace.
    Synthetic links for PoC demos—kept clearly separate.
    """
    if seed is not None:
        random.seed(seed)

    n = max(5, min(10, int(count)))
    for i in range(n):
        target = URIRef(str(EX) + f"demo-{i+1}")
        pred = random.choice(_SAMPLE_RELATION_PROPS)
        g.add((subj, pred, target))
        g.add((target, RDF.type, UNI.Clause))
        g.add((target, RDFS.label, Literal(f"Demo target #{i+1}")))
        g.add((target, UNI.sample, Literal(True, datatype=XSD.boolean)))

# ---------- SHACL validation ----------
def shacl_validate(g: Graph, shapes_path: str) -> Tuple[bool, Graph, str]:
    """
    Run pyshacl.validate on the given graph using shapes at shapes_path.
    """
    from pyshacl import validate  # lazy import
    shapes = Graph()
    shapes.parse(shapes_path, format="turtle")

    conforms, results_graph, results_text = validate(
        g,
        shacl_graph=shapes,
        inference="rdfs",
        abort_on_first=False,
        meta_shacl=False,
        advanced=True,
        js=False,
        debug=False,
    )
    return conforms, results_graph, results_text

# ---------- IO ----------
def _read_meta_items(path: str) -> Iterable[Dict]:
    """
    Accepts either:
      - a JSON file with an object (single meta) or a list of objects
      - a JSONL file (one JSON object per line)
    """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return []
    # try JSON (object or list)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return [obj]
        if isinstance(obj, list):
            return obj
    except Exception:
        pass
    # fallback: JSONL
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        items.append(json.loads(line))
    return items

# ---------- CLI ----------
def export_cli() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="metadata JSON/JSONL path")
    ap.add_argument("--out", dest="out", required=True, help="output TTL path")
    ap.add_argument("--inject-samples", action="store_true", help="inject 5~10 EX:* demo relation triples")
    ap.add_argument("--sample-count", type=int, default=6, help="how many sample relations (5~10 recommended)")
    ap.add_argument("--validate", action="store_true", help="run SHACL validation after export")
    ap.add_argument("--shapes", default="ontology/shapes.ttl", help="path to SHACL shapes TTL")
    args = ap.parse_args()

    g_all = Graph()
    g_all.bind("uni", UNI)
    g_all.bind("id", ID)
    g_all.bind("owl", OWL)
    g_all.bind("ex", EX)

    metas = list(_read_meta_items(args.inp))
    for m in metas:
        g_one, subj = chunk_meta_to_rdf(m)
        g_all += g_one
        if args.inject_samples:
            inject_sample_relations(g_all, subj=subj, count=args.sample_count)

    g_all.serialize(destination=args.out, format="turtle")
    print(f"✅ wrote: {args.out}")

    if args.validate:
        try:
            conforms, _rg, rtxt = shacl_validate(g_all, args.shapes)
            if conforms:
                print("✅ SHACL Validation Passed")
                return 0
            else:
                print("❌ SHACL Validation Failed")
                print(rtxt)
                return 2
        except FileNotFoundError:
            print(f"⚠️  shapes not found: {args.shapes} — skipped validation")
            return 0
    return 0

if __name__ == "__main__":
    raise SystemExit(export_cli())
