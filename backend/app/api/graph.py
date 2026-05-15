"""Graph API: ontology generation, graph build, graph data retrieval."""
from flask import Blueprint, jsonify, request

from app.services.graph_builder import GraphBuilderService
from app.services.ontology_generator import OntologyGenerator
from app.services.text_processor import TextProcessor

graph_bp = Blueprint("graph", __name__)

_graph_service = GraphBuilderService()


def _ok(data, **extra):
    return jsonify({"success": True, "data": data, **extra})


def _err(message, status=400):
    return jsonify({"success": False, "error": message}), status


@graph_bp.route("/health", methods=["GET"])
def health():
    return _ok({"service": "graph", "status": "ok"})


@graph_bp.route("/ontology/generate", methods=["POST"])
def ontology_generate():
    payload = request.get_json(silent=True) or {}
    text = payload.get("text") or payload.get("source_text") or ""
    project = payload.get("project_name") or payload.get("simulation_requirement") or "MiroFish Project"
    if not text.strip():
        return _err("text is required", 400)
    try:
        generator = OntologyGenerator()
        ontology = generator.generate(
            document_texts=[text],
            simulation_requirement=project,
        )
        return _ok(ontology)
    except Exception as exc:  # noqa: BLE001
        return _err(f"ontology generation failed: {exc}", 500)


@graph_bp.route("/build", methods=["POST"])
def graph_build():
    payload = request.get_json(silent=True) or {}
    text = payload.get("text") or payload.get("source_text") or ""
    ontology = payload.get("ontology") or {}
    name = payload.get("name") or "MiroFish Graph"
    if not text.strip():
        return _err("text is required", 400)
    try:
        graph_id = _graph_service.create_graph(name)
        if ontology:
            _graph_service.set_ontology(graph_id, ontology)
        chunks = TextProcessor.split_text(text, chunk_size=500, overlap=50)
        _graph_service.add_text_batches(graph_id, chunks)
        _graph_service._wait_for_episodes(graph_id)
        data = _graph_service.get_graph_data(graph_id)
        return _ok(data, graph_id=graph_id)
    except Exception as exc:  # noqa: BLE001
        return _err(f"graph build failed: {exc}", 500)


@graph_bp.route("/<graph_id>/data", methods=["GET"])
def graph_data(graph_id: str):
    try:
        data = _graph_service.get_graph_data(graph_id)
        return _ok(data, graph_id=graph_id)
    except Exception as exc:  # noqa: BLE001
        return _err(f"failed to load graph: {exc}", 404)

