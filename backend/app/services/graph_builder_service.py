# backend/app/services/graph_builder_service.py
from typing import Any, Dict, List, Optional
from app.services.graph_builder import GraphBuilderService as _BaseBuilder


def _strip_nulls(value):
    if isinstance(value, str):
        return value.replace("\x00", "").replace("\\u0000", "")
    if isinstance(value, dict):
        return {k: _strip_nulls(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_nulls(v) for v in value]
    return value


class GraphBuilderService(_BaseBuilder):
    """Facade exposing build_from_chunks() expected by app/api/graph.py."""

    def build_from_chunks(
        self,
        chunks: List[str],
        ontology: Optional[Dict[str, Any]] = None,
        graph_name: str = "graph",
    ) -> Dict[str, Any]:
        # sanitize NULs that break Postgres text columns
        clean_chunks = [_strip_nulls(c) for c in (chunks or []) if c]
        clean_ontology = _strip_nulls(ontology) if ontology else None

        graph_id = self.create_graph(graph_name)
        if clean_ontology:
            self.set_ontology(graph_id, clean_ontology)

        episode_ids = self.add_text_batches(graph_id, clean_chunks)
        try:
            self._wait_for_episodes(graph_id, episode_ids)
        except Exception:
            pass

        data = self.get_graph_data(graph_id)
        return {
            "graph_id": graph_id,
            "nodes": _strip_nulls(data.get("nodes") or []),
            "edges": _strip_nulls(data.get("edges") or []),
        }
