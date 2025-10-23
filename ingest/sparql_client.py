import os
import requests
from typing import Any, Dict, Optional

FUSEKI_BASE = os.getenv("FUSEKI_BASE", "http://localhost:3030")
DATASET = os.getenv("FUSEKI_DATASET", "ds")
QUERY_URL = f"{FUSEKI_BASE}/{DATASET}/query"
UPDATE_URL = f"{FUSEKI_BASE}/{DATASET}/update"

ADMIN_USER = os.getenv("FUSEKI_USER", "")
ADMIN_PASS = os.getenv("FUSEKI_PASS", "")

AUTH = (ADMIN_USER, ADMIN_PASS) if ADMIN_USER and ADMIN_PASS else None
HEADERS = {"Accept": "application/sparql-results+json"}

def sparql_query(query: str, timeout: int = 30) -> Dict[str, Any]:
    r = requests.get(QUERY_URL, params={"query": query}, headers=HEADERS, auth=AUTH, timeout=timeout)
    r.raise_for_status()
    return r.json()

def sparql_update(update: str, timeout: int = 30) -> None:
    r = requests.get(UPDATE_URL, params={"update": update}, auth=AUTH, timeout=timeout)
    r.raise_for_status()

def latest_clause(article: int, clause: Optional[int], graph_uri: str) -> Optional[Dict[str, str]]:
    q = f"""
    SELECT ?clause ?article ?clauseNo ?eff ?label ?page ?src WHERE {{
      GRAPH <{graph_uri}> {{
        ?clause a <https://kg.khu.ac.kr/uni#Clause> ;
                <https://kg.khu.ac.kr/uni#article> ?article ;
                <https://kg.khu.ac.kr/uni#effectiveFrom> ?eff .
        OPTIONAL {{ ?clause <https://kg.khu.ac.kr/uni#clause> ?clauseNo }}
        OPTIONAL {{ ?clause <http://www.w3.org/2000/01/rdf-schema#label> ?label }}
        OPTIONAL {{ ?clause <https://kg.khu.ac.kr/uni#page> ?page }}
        OPTIONAL {{ ?clause <http://purl.org/dc/terms/source> ?src }}
        FILTER(?article = {article})
        {"FILTER(BOUND(?clauseNo) && ?clauseNo = " + str(clause) + ")" if clause is not None else ""}
      }}
    }}
    ORDER BY DESC(?eff)
    LIMIT 1
    """
    res = sparql_query(q)
    b = res.get("results", {}).get("bindings", [])
    if not b:
        return None
    row = b[0]
    def g(key): 
        v = row.get(key)
        return v and v.get("value")
    return {
        "uri": g("clause"),
        "article": g("article"),
        "clauseNo": g("clauseNo"),
        "effectiveFrom": g("eff"),
        "label": g("label"),
        "page": g("page"),
        "source": g("src"),
    }

def clause_meta(clause_uri: str, graph_uri: str) -> Dict[str, Optional[str]]:
    q = f"""
    SELECT ?label ?src ?page ?md5 WHERE {{
      GRAPH <{graph_uri}> {{
        OPTIONAL {{ <{clause_uri}> <http://www.w3.org/2000/01/rdf-schema#label> ?label }}
        OPTIONAL {{ <{clause_uri}> <http://purl.org/dc/terms/source> ?src }}
        OPTIONAL {{ <{clause_uri}> <https://kg.khu.ac.kr/uni#page> ?page }}
        OPTIONAL {{ <{clause_uri}> <https://kg.khu.ac.kr/uni#md5> ?md5 }}
      }}
    }}
    LIMIT 1
    """
    res = sparql_query(q)
    b = res.get("results", {}).get("bindings", [])
    if not b:
        return {"label": None, "src": None, "page": None, "md5": None}
    row = b[0]
    def g(key):
        v = row.get(key)
        return v and v.get("value")
    return {"label": g("label"), "src": g("src"), "page": g("page"), "md5": g("md5")}
