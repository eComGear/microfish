"""Compatibility wrapper for ontology generation."""

from __future__ import annotations

from typing import Any, Dict

from .ontology_generator import OntologyGenerator


def generate_ontology(
    text: str,
    project_name: str = "MiroFish Project",
) -> Dict[str, Any]:
    generator = OntologyGenerator()
    return generator.generate(
        document_texts=[text or ""],
        simulation_requirement=project_name or "Generate ontology for social simulation",
    )
