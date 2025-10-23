# 템플릿: {{CLAUSE_URI}} / {{GRAPH_URI}}
SELECT ?label ?src ?page ?md5 WHERE {
  GRAPH <{{GRAPH_URI}}> {
    OPTIONAL { <{{CLAUSE_URI}}> <http://www.w3.org/2000/01/rdf-schema#label> ?label }
    OPTIONAL { <{{CLAUSE_URI}}> <http://purl.org/dc/terms/source> ?src }
    OPTIONAL { <{{CLAUSE_URI}}> <https://kg.khu.ac.kr/uni#page> ?page }
    OPTIONAL { <{{CLAUSE_URI}}> <https://kg.khu.ac.kr/uni#md5> ?md5 }
  }
}
LIMIT 1
