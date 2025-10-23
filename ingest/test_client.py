# ingest/test_client.py
from sparql_client import latest_clause, clause_meta

GRAPH = "http://kg.khu.ac.kr/graph/regulations"

row = latest_clause(article=30, clause=2, graph_uri=GRAPH)
print("Latest:", row)

if row and row["uri"]:
    meta = clause_meta(row["uri"], GRAPH)
    print("Meta:", meta)
