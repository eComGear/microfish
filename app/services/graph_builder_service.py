"""
Graph builder facade.

backend/app/api/graph.py does:
    from app.services.graph_builder_service import GraphBuilderService

This module provides that class and delegates to whatever ontology/graph
generators already exist in the project. Missing generators degrade to a
safe stub instead of crashing the worker.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class GraphBuilderService:
    def __init__(
        self,
        project_id: str,
        payload: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ):
        self.project_id = project_id
        self.payload = payload or {}
        self.options = kwargs

    # ---- ontology ----------------------------------------------------------
    def _build_ontology(self) -> Dict[str, Any]:
        try:
            from app.ontology_generator import generate_ontology  # type: ignore
            return generate_ontology(self.payload)
        except ImportError:
            pass
        except Exception as e:
            log.exception("ontology generation failed: %s", e)
            return {"entities": [], "relations": [], "error": str(e)}

        # Fallback: try a class-based generator
        try:
            from app.ontology_generator import OntologyGenerator  # type: ignore
            return OntologyGenerator(self.payload).generate()
        except Exception as e:
            log.warning("no ontology generator available: %s", e)
            return {"entities": [], "relations": []}

    # ---- graph -------------------------------------------------------------
    def _build_graph(self, ontology: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from app.graph_generator import generate_graph  # type: ignore
            return generate_graph(ontology, self.payload)
        except ImportError:
            pass
        except Exception as e:
            log.exception("graph generation failed: %s", e)
            return {"nodes": [], "edges": [], "error": str(e)}

        try:
            from app.graph_generator import GraphGenerator  # type: ignore
            return GraphGenerator(ontology, self.payload).generate()
        except Exception as e:
            log.warning("no graph generator available: %s", e)
            # Derive a minimal graph from ontology entities so UI isn't empty
            entities = ontology.get("entities", []) or []
            relations = ontology.get("relations", []) or []
            nodes = [
                {"id": (ent.get("id") or ent.get("name") or f"n{i}"),
                 "label": ent.get("name") or ent.get("label") or f"Node {i}",
                 "type": ent.get("type")}
                for i, ent in enumerate(entities)
            ]
            edges = [
                {"id": rel.get("id") or f"e{i}",
                 "source": rel.get("source") or rel.get("from"),
                 "target": rel.get("target") or rel.get("to"),
                 "label": rel.get("type") or rel.get("label")}
                for i, rel in enumerate(relations)
            ]
            return {"nodes": nodes, "edges": edges}

    # ---- public API --------------------------------------------------------
    def build(self) -> Dict[str, Any]:
        ontology = self._build_ontology()
        graph = self._build_graph(ontology)
        return {
            "project_id": self.project_id,
            "ontology": ontology,
            "graph": graph,
        }

    # api/graph.py may call .run() — alias to .build()
    def run(self) -> Dict[str, Any]:
        return self.build()

    # Some callers use a classmethod factory
    @classmethod
    def from_payload(cls, project_id: str, payload: Dict[str, Any]) -> "GraphBuilderService":
        return cls(project_id, payload)

