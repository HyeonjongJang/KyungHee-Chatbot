from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, XSD

UNI = Namespace("http://example.org/uni#")

def chunk_meta_to_rdf(meta: dict) -> Graph:
    """
    Minimal skeleton for Phase 5.
    Converts a single JSON chunk's metadata to an RDF graph.
    """
    g = Graph()
    uri = URIRef(meta["uri"])
    # Treat chunk as a Clause instance for now
    g.add((uri, RDF.type, UNI.Clause))

    # Program / Cohort linkage (normalize upstream)
    if meta.get("program"):
        g.add((uri, UNI.appliesToProgram, URIRef(f"http://example.org/uni#{meta['program']}")))
    if meta.get("cohort"):
        g.add((uri, UNI.appliesToCohort, URIRef(f"http://example.org/uni#{meta['cohort']}")))

    # Temporal scope (use versionDate as a minimal effectiveFrom)
    if meta.get("versionDate"):
        g.add((uri, UNI.effectiveFrom, Literal(meta["versionDate"], datatype=XSD.date)))

    return g
