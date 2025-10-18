from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS, XSD, OWL

# ✅ 어휘(클래스/프로퍼티)
UNI = Namespace("https://kg.khu.ac.kr/uni#")
# ✅ 인스턴스(개체)
ID  = Namespace("https://kg.khu.ac.kr/id/")

def chunk_meta_to_rdf(meta: dict) -> Graph:
    g = Graph()
    g.bind("uni", UNI)
    g.bind("id", ID)
    g.bind("owl", OWL)

    # --- 주피(subject) 선택: clauseUri > articleUri > URN ---
    subj = URIRef(meta.get("clauseUri") or meta.get("articleUri") or meta["uri"])
    g.add((subj, RDF.type, UNI.Clause))

    # URN ↔ HTTP 동등성
    if meta.get("uri"):
        g.add((URIRef(meta["uri"]), OWL.sameAs, subj))

    # Program / Cohort 인스턴스화
    prog = meta.get("program")
    if prog:
        prog_uri = URIRef(ID[f"program/{prog}"])  # ex) .../id/program/IME_MS
        g.add((prog_uri, RDF.type, UNI.Program))
        g.add((prog_uri, RDFS.label, Literal(prog)))
        g.add((subj, UNI.appliesToProgram, prog_uri))

    coh = meta.get("cohort")
    if coh:
        # Cohort_2023 → 2023
        year = str(coh).replace("Cohort_", "")
        coh_uri = URIRef(ID[f"cohort/{year}"])    # ex) .../id/cohort/2023
        g.add((coh_uri, RDF.type, UNI.Cohort))
        g.add((coh_uri, RDFS.label, Literal(coh)))
        g.add((subj, UNI.appliesToCohort, coh_uri))

    # 시간 속성
    if meta.get("versionDate"):
        g.add((subj, UNI.versionDate, Literal(meta["versionDate"], datatype=XSD.date)))
    if meta.get("effectiveFrom"):
        g.add((subj, UNI.effectiveFrom, Literal(meta["effectiveFrom"], datatype=XSD.date)))
    if meta.get("effectiveUntil"):
        g.add((subj, UNI.effectiveUntil, Literal(meta["effectiveUntil"], datatype=XSD.date)))

    # 관계: overrides / cites / hasExceptionFor
    for k, pred in (("overrides", UNI.overrides), ("cites", UNI.cites)):
        for u in meta.get(k) or []:
            try:
                g.add((subj, pred, URIRef(u)))
            except Exception:
                pass

    for exc in (meta.get("hasExceptionFor") or []):
        try:
            if isinstance(exc, str) and exc.startswith("http"):
                g.add((subj, UNI.hasExceptionFor, URIRef(exc)))
            else:
                g.add((subj, UNI.hasExceptionFor, Literal(exc)))
        except Exception:
            pass

    return g
