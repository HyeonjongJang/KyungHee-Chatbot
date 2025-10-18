#!/usr/bin/env python3
import sys
import argparse
from rdflib import Graph
from pyshacl import validate

def validate_rdf(data_path: str, shapes_path: str) -> int:
    data_graph = Graph()
    data_graph.parse(data_path, format="turtle")

    shapes_graph = Graph()
    shapes_graph.parse(shapes_path, format="turtle")

    conforms, results_graph, results_text = validate(
        data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        advanced=True,
        abort_on_first=False,
    )

    if conforms:
        print("✅ SHACL Validation Passed")
        return 0
    else:
        print("❌ SHACL Validation Failed")
        print(results_text)
        return 1

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="RDF Turtle file to validate")
    ap.add_argument("--shapes", default="ontology/shapes.ttl", help="SHACL shapes ttl")
    args = ap.parse_args()
    sys.exit(validate_rdf(args.data, args.shapes))
