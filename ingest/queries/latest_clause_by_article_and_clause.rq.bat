# 템플릿: {{ARTICLE}} / {{CLAUSE}} / {{GRAPH_URI}}
SELECT ?clause ?article ?clauseNo ?eff ?label ?page ?src WHERE {
  GRAPH <{{GRAPH_URI}}> {
    ?clause a <https://kg.khu.ac.kr/uni#Clause> ;
            <https://kg.khu.ac.kr/uni#article> ?article ;
            <https://kg.khu.ac.kr/uni#effectiveFrom> ?eff .
    OPTIONAL { ?clause <https://kg.khu.ac.kr/uni#clause> ?clauseNo }
    OPTIONAL { ?clause <http://www.w3.org/2000/01/rdf-schema#label> ?label }
    OPTIONAL { ?clause <https://kg.khu.ac.kr/uni#page> ?page }
    OPTIONAL { ?clause <http://purl.org/dc/terms/source> ?src }
    FILTER(?article = {{ARTICLE}})
    FILTER(BOUND(?clauseNo) && ?clauseNo = {{CLAUSE}})
  }
}
ORDER BY DESC(?eff)
LIMIT 1
