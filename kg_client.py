#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kg_client.py — Fuseki(SPARQL) client helpers for KyungHee-Chatbot

Features
- Config from Streamlit secrets with env fallback
- Robust SPARQL GET with retry and optional BasicAuth
- Guardrail: require_rows()
- Query helpers for common intents:
    * q_article15_details()
    * q_since_date()
    * q_article15_files_pages()
    * q_article15_sameas()
    * q_count_article_or_clause_none()
    * q_undergrad_top5_for_cohort()  # example for UG 2025
- Legacy-compatible get_applicable_clauses()
"""

from __future__ import annotations

import os
import time
import json
import logging
from typing import Dict, List, Optional, Any, Callable, Tuple

import requests

# Streamlit may not always be present (e.g., CLI tests).
try:
    import streamlit as st  # type: ignore
    _HAS_ST = True
except Exception:
    _HAS_ST = False

# ---------- Config ----------

def _get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    """Get from Streamlit secrets first, then environment variables."""
    if _HAS_ST:
        try:
            if name in st.secrets:
                return st.secrets.get(name)  # type: ignore
        except Exception:
            pass
    return os.environ.get(name, default)

def get_config() -> Dict[str, str]:
    """
    Returns resolved configuration.
    Required:
        FUSEKI_BASE (e.g., http://localhost:3030)
        FUSEKI_DATASET (e.g., ds)
        GRAPH_URI (e.g., http://kg.khu.ac.kr/graph/regulations)
    Optional:
        FUSEKI_USER / FUSEKI_PASS
        FUSEKI_TIMEOUT_SEC
        FUSEKI_RETRIES
    """
    cfg = {
        "FUSEKI_BASE"   : _get_secret("FUSEKI_BASE", "http://localhost:3030"),
        "FUSEKI_DATASET": _get_secret("FUSEKI_DATASET", "ds"),
        "GRAPH_URI"     : _get_secret("GRAPH_URI", "http://kg.khu.ac.kr/graph/regulations"),
        "FUSEKI_USER"   : _get_secret("FUSEKI_USER", None),
        "FUSEKI_PASS"   : _get_secret("FUSEKI_PASS", None),
        "FUSEKI_TIMEOUT_SEC": _get_secret("FUSEKI_TIMEOUT_SEC", "20"),
        "FUSEKI_RETRIES"    : _get_secret("FUSEKI_RETRIES", "2"),
    }
    return cfg  # type: ignore


# ---------- Utilities ----------

def _retry(fn: Callable[[], Any], retries: int = 2, backoff: float = 0.7) -> Any:
    last_err = None
    for i in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if i < retries:
                time.sleep(backoff * (2 ** i))
    if last_err:
        raise last_err

def _basic_auth(cfg: Dict[str, str]) -> Optional[Tuple[str, str]]:
    user = cfg.get("FUSEKI_USER")
    pw = cfg.get("FUSEKI_PASS")
    if user and pw:
        return (user, pw)
    return None

def _sparql_raw(query: str, cfg: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Low-level SPARQL GET.
    Returns JSON of SPARQL results.
    Raises requests.HTTPError on non-200.
    """
    if cfg is None:
        cfg = get_config()
    base = cfg["FUSEKI_BASE"].rstrip("/")
    ds   = cfg["FUSEKI_DATASET"].strip("/")
    url  = f"{base}/{ds}/query"
    timeout = float(cfg.get("FUSEKI_TIMEOUT_SEC", "20"))
    auth = _basic_auth(cfg)
    headers = {
        "Accept": "application/sparql-results+json"
    }
    def _do():
        r = requests.get(url, params={"query": query}, headers=headers, auth=auth, timeout=timeout)
        r.raise_for_status()
        return r.json()
    retries = int(cfg.get("FUSEKI_RETRIES", "2"))
    return _retry(_do, retries=retries)

def _val(binding: Dict[str, Any], key: str, default: Optional[str] = None) -> Optional[str]:
    """Extract 'value' from SPARQL JSON binding safely."""
    x = binding.get(key)
    if not x:
        return default
    return x.get("value", default)

def require_rows(rows: List[Dict[str, Any]], msg: str = "데이터가 없습니다. 필터를 바꿔보세요.") -> List[Dict[str, Any]]:
    """Guardrail: refuse to proceed with empty results in UI code."""
    if not rows:
        raise ValueError(msg)
    return rows


# ---------- Query helpers (domain) ----------

def q_article15_details(category: str = "regulations", cfg: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    All clauses for Article 15 in a category with label/src/page/effFrom.
    """
    if cfg is None:
        cfg = get_config()
    graph = cfg["GRAPH_URI"]
    q = f"""
    PREFIX uni: <https://kg.khu.ac.kr/uni#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX dct: <http://purl.org/dc/terms/>
    SELECT ?s ?article ?clause ?label ?src ?page ?effFrom WHERE {{
      GRAPH <{graph}> {{
        ?s a uni:Clause ;
           uni:category "{category}" ;
           uni:article 15 .
        OPTIONAL {{ ?s uni:clause ?clause }}
        OPTIONAL {{ ?s rdfs:label ?label }}
        OPTIONAL {{ ?s dct:source ?src }}
        OPTIONAL {{ ?s uni:page ?page }}
        OPTIONAL {{ ?s uni:effectiveFrom ?effFrom }}
        BIND(15 AS ?article)
      }}
    }} ORDER BY ?clause
    """
    res = _sparql_raw(q, cfg)
    return res.get("results", {}).get("bindings", [])


def q_since_date(category: str, cohort: str, since: str, cfg: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    Clauses for (category, cohort) with effectiveFrom >= since.
    Example: q_since_date("regulations", "2025", "2025-04-30")
    """
    if cfg is None:
        cfg = get_config()
    graph = cfg["GRAPH_URI"]
    q = f"""
    PREFIX uni: <https://kg.khu.ac.kr/uni#>
    PREFIX dct: <http://purl.org/dc/terms/>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    SELECT ?s ?article ?clause ?effFrom ?src ?page WHERE {{
      GRAPH <{graph}> {{
        ?s a uni:Clause ;
           uni:category "{category}" ;
           uni:appliesToCohort "{cohort}" ;
           uni:effectiveFrom ?effFrom .
        FILTER ( ?effFrom >= "{since}"^^xsd:date )
        OPTIONAL {{ ?s uni:article ?article }}
        OPTIONAL {{ ?s uni:clause ?clause }}
        OPTIONAL {{ ?s dct:source ?src }}
        OPTIONAL {{ ?s uni:page ?page }}
      }}
    }} ORDER BY ?effFrom ?article ?clause
    """
    res = _sparql_raw(q, cfg)
    return res.get("results", {}).get("bindings", [])


def q_article15_files_pages(category: str = "regulations", cfg: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    DISTINCT (source, page) pairs for Article 15 in the category.
    """
    if cfg is None:
        cfg = get_config()
    graph = cfg["GRAPH_URI"]
    q = f"""
    PREFIX uni: <https://kg.khu.ac.kr/uni#>
    PREFIX dct: <http://purl.org/dc/terms/>
    SELECT DISTINCT ?src ?page WHERE {{
      GRAPH <{graph}> {{
        ?s a uni:Clause ;
           uni:category "{category}" ;
           uni:article 15 .
        OPTIONAL {{ ?s dct:source ?src }}
        OPTIONAL {{ ?s uni:page ?page }}
      }}
    }} ORDER BY ?src ?page
    """
    res = _sparql_raw(q, cfg)
    return res.get("results", {}).get("bindings", [])


def q_article15_sameas(category: str = "regulations", cfg: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    Article 15 clauses with URN owl:sameAs links.
    """
    if cfg is None:
        cfg = get_config()
    graph = cfg["GRAPH_URI"]
    q = f"""
    PREFIX uni: <https://kg.khu.ac.kr/uni#>
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    SELECT ?s ?urn WHERE {{
      GRAPH <{graph}> {{
        ?s a uni:Clause ;
           uni:category "{category}" ;
           uni:article 15 ;
           owl:sameAs ?urn .
        FILTER(STRSTARTS(STR(?urn), "urn:khu:"))
      }}
    }} LIMIT 50
    """
    res = _sparql_raw(q, cfg)
    return res.get("results", {}).get("bindings", [])


def q_count_article_or_clause_none(category: str = "regulations", cfg: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    Count of records missing article or clause.
    """
    if cfg is None:
        cfg = get_config()
    graph = cfg["GRAPH_URI"]
    q = f"""
    PREFIX uni: <https://kg.khu.ac.kr/uni#>
    SELECT (COUNT(*) AS ?n) WHERE {{
      GRAPH <{graph}> {{
        ?s a uni:Clause ;
           uni:category "{category}" .
        FILTER ( !EXISTS{{?s uni:article ?a}} || !EXISTS{{?s uni:clause ?c}} )
      }}
    }}
    """
    res = _sparql_raw(q, cfg)
    return res.get("results", {}).get("bindings", [])


def q_undergrad_top5_for_cohort(cohort: str = "2025", cfg: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    Example: top 5 undergrad_rules clauses for given cohort.
    """
    if cfg is None:
        cfg = get_config()
    graph = cfg["GRAPH_URI"]
    q = f"""
    PREFIX uni: <https://kg.khu.ac.kr/uni#>
    PREFIX dct: <http://purl.org/dc/terms/>
    SELECT ?s ?article ?clause ?effFrom ?src WHERE {{
      GRAPH <{graph}> {{
        ?s a uni:Clause ;
           uni:category "undergrad_rules" ;
           uni:appliesToCohort "{cohort}" .
        OPTIONAL {{ ?s uni:article ?article }}
        OPTIONAL {{ ?s uni:clause ?clause }}
        OPTIONAL {{ ?s uni:effectiveFrom ?effFrom }}
        OPTIONAL {{ ?s dct:source ?src }}
      }}
    }} ORDER BY ?effFrom ?article ?clause
    LIMIT 5
    """
    res = _sparql_raw(q, cfg)
    return res.get("results", {}).get("bindings", [])


# ---------- Legacy-style helper (kept for compatibility) ----------

def get_applicable_clauses(program: str, cohort: str, ref_date: str,
                           article: Optional[int] = None,
                           category: str = "regulations",
                           cfg: Optional[Dict[str, str]] = None) -> List[str]:
    """
    Returns list of clause URIs (HTTP) for (program, cohort, effectiveFrom <= ref_date).
    If article is provided, filter on uni:article = article.
    """
    if cfg is None:
        cfg = get_config()
    graph = cfg["GRAPH_URI"]
    # Build article filter
    article_filter = f"FILTER(?article = {article})" if article is not None else ""
    q = f"""
    PREFIX uni: <https://kg.khu.ac.kr/uni#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    SELECT ?s WHERE {{
      GRAPH <{graph}> {{
        ?s a uni:Clause ;
           uni:category "{category}" ;
           uni:appliesToCohort "{cohort}" ;
           uni:appliesToProgram "{program}" ;
           uni:effectiveFrom ?effFrom .
        OPTIONAL {{ ?s uni:article ?article }}
        FILTER ( ?effFrom <= "{ref_date}"^^xsd:date )
        {article_filter}
      }}
    }} ORDER BY ?effFrom
    """
    res = _sparql_raw(q, cfg)
    rows = res.get("results", {}).get("bindings", [])
    # Return just the subject URIs
    uris: List[str] = []
    for b in rows:
        v = _val(b, "s")
        if v:
            uris.append(v)
    return uris


# ---------- Convenience formatters (optional) ----------

def bindings_to_table(rows: List[Dict[str, Any]], cols: List[str]) -> List[List[str]]:
    """
    Convert SPARQL JSON bindings into a simple 2D list [[...], ...] for table render.
    """
    out: List[List[str]] = []
    for b in rows:
        out.append([_val(b, c, "") or "" for c in cols])
    return out


# ---------- Simple self-test (optional) ----------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        cfg = get_config()
        print("[cfg]", json.dumps(cfg, ensure_ascii=False, indent=2))
        # basic ping query
        q = "SELECT (COUNT(*) AS ?n) WHERE { GRAPH <" + cfg["GRAPH_URI"] + "> { ?s a <https://kg.khu.ac.kr/uni#Clause> . } }"
        res = _sparql_raw(q, cfg)
        print("[count]", res)
    except Exception as e:
        print("[ERR]", e)
