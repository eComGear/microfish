"""Compatibility facade for backend/app/api/graph.py.

graph.py imports `app.services.graph_builder_service.GraphBuilderService` and
calls `build_from_chunks(...)`, but upstream only ships `graph_builder.py`.
This module bridges the gap without touching the API route.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .graph_builder import GraphBuilderService as BaseGraphBuilderService


class GraphBuilderService(BaseGraphBuilderService):
    def build_from_chunks(
        self,
        chunks: List[str],
        ontology: Optional[Dict[str, Any]] = None,
        graph_name: str = "MiroFish Graph",
        batch_size: int = 3,
    ) -> Dict[str, Any]:
        graph_id = self.create_graph(graph_name)

        if ontology:
            try:
                self.set_ontology(graph_id, ontology)
            except Exception:
                # Non-fatal: continue without custom ontology
                pass

        clean_chunks = [
            c.replace("\x00", "")
            for c in (chunks or [])
            if isinstance(c, str) and c.strip()
        ]

        episode_uuids: List[str] = []
        if clean_chunks:
            episode_uuids = self.add_text_batches(
                graph_id=graph_id,
                chunks=clean_chunks,
                batch_size=batch_size,
            )

        try:
            self._wait_for_episodes(episode_uuids)
        except Exception:
            pass

        graph = self.get_graph_data(graph_id) or {}
        graph.setdefault("graph_id", graph_id)
        graph.setdefault("nodes", [])
        graph.setdefault("edges", [])
        return graph

