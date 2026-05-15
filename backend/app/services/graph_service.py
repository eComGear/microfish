"""Compatibility wrapper for synchronous graph building."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .graph_builder import GraphBuilderService
from .text_processor import TextProcessor


def build_graph(
    source_text: str,
    ontology: Dict[str, Any],
    on_progress: Optional[Callable[[int], None]] = None,
) -> Dict[str, Any]:
    service = GraphBuilderService()

    if on_progress:
        on_progress(10)

    graph_id = service.create_graph("MiroFish Graph")

    if on_progress:
        on_progress(15)

    service.set_ontology(graph_id, ontology or {})

    if on_progress:
        on_progress(20)

    chunks = TextProcessor.split_text(source_text or "", chunk_size=500, overlap=50)

    episode_uuids = service.add_text_batches(
        graph_id,
        chunks,
        batch_size=3,
        progress_callback=(
            lambda _msg, progress: on_progress(20 + int(progress * 40))
            if on_progress
            else None
        ),
    )

    if on_progress:
        on_progress(60)

    service._wait_for_episodes(
        episode_uuids,
        progress_callback=(
            lambda _msg, progress: on_progress(60 + int(progress * 30))
            if on_progress
            else None
        ),
    )

    if on_progress:
        on_progress(90)

    graph = service.get_graph_data(graph_id)

    if on_progress:
        on_progress(100)

    return graph
