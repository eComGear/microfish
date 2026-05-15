import logging
import os
import tempfile
import threading
import uuid
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from app.services.graph_builder_service import GraphBuilderService
from app.services.ontology_service import OntologyService
from app.store import (
    get_graph,
    get_project,
    get_task,
    save_graph,
    save_project,
    save_task,
)

log = logging.getLogger(__name__)

bp = Blueprint("graph", __name__, url_prefix="/api/graph")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@bp.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "graph"})


# ---------------------------------------------------------------------------
# Ontology generation
# ---------------------------------------------------------------------------
@bp.route("/ontology/generate", methods=["POST"])
def ontology_generate():
    try:
        files = request.files.getlist("files") or []
        simulation_requirement = request.form.get("simulation_requirement", "") or ""
        project_name = request.form.get("project_name", "MiroFish Project") or "MiroFish Project"

        if not files:
            return jsonify({"error": "no files uploaded"}), 400

        chunks: List[str] = []
        upload_dir = os.environ.get("UPLOAD_DIR", tempfile.gettempdir())
        os.makedirs(upload_dir, exist_ok=True)

        for f in files:
            dest = os.path.join(upload_dir, f"{uuid.uuid4()}_{f.filename}")
            f.save(dest)
            try:
                with open(dest, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read().replace("\x00", "")
            except Exception as e:
                log.warning("failed to read uploaded file %s: %s", dest, e)
                text = ""
            if text.strip():
                chunks.append(text)

        ontology_service = OntologyService()
        ontology = ontology_service.generate_from_chunks(
            chunks=chunks,
            requirement=simulation_requirement,
        )

        project_id = str(uuid.uuid4())
        save_project(
            project_id,
            {
                "project_id": project_id,
                "name": project_name,
                "simulation_requirement": simulation_requirement,
                "ontology": ontology,
                "chunks": chunks,
            },
        )

        return jsonify(
            {
                "project_id": project_id,
                "ontology": ontology,
                "chunks_count": len(chunks),
            }
        )
    except Exception as e:
        log.exception("ontology_generate failed")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Graph build (async via background thread + task row)
# ---------------------------------------------------------------------------
def _run_build(task_id: str, project_id: str, graph_name: str, ontology: Optional[Dict[str, Any]]):
    try:
        save_task(task_id, {"task_id": task_id, "status": "running", "project_id": project_id})

        proj = get_project(project_id) or {}
        chunks: List[str] = proj.get("chunks") or []
        if not chunks:
            raise RuntimeError(f"project {project_id} has no chunks; run /api/graph/ontology/generate first")

        builder = GraphBuilderService()
        graph_data: Dict[str, Any] = builder.build_from_chunks(
            chunks=chunks,
            ontology=ontology or proj.get("ontology"),
            graph_name=graph_name,
        ) or {}

        # CRITICAL: use the Zep graph_id returned by the builder.
        # Previously this was overwritten with uuid.uuid4(), which is why
        # later calls to zep.graph.node.get_by_graph_id() returned 404.
        gid = graph_data.get("graph_id")
        if not gid:
            raise RuntimeError(
                "graph build completed but GraphBuilderService returned no Zep graph_id"
            )

        nodes = graph_data.get("nodes") or []
        edges = graph_data.get("edges") or []

        save_graph(
            gid,
            {
                "graph_id": gid,
                "project_id": project_id,
                "name": graph_name,
                "nodes": nodes,
                "edges": edges,
            },
        )

        # Persist the Zep graph_id back onto the project so /api/simulation/* can resolve it.
        proj["graph_id"] = gid
        save_project(project_id, proj)

        save_task(
            task_id,
            {
                "task_id": task_id,
                "status": "succeeded",
                "project_id": project_id,
                "graph_id": gid,
                "result": {
                    "graph_id": gid,
                    "nodes_count": len(nodes),
                    "edges_count": len(edges),
                },
            },
        )
    except Exception as e:
        log.exception("graph build failed for task %s", task_id)
        save_task(
            task_id,
            {
                "task_id": task_id,
                "status": "failed",
                "project_id": project_id,
                "error": str(e),
            },
        )


@bp.route("/build", methods=["POST"])
def graph_build():
    try:
        data = request.get_json(silent=True) or {}
        project_id = data.get("project_id")
        graph_name = data.get("graph_name") or "MiroFish Graph"
        ontology = data.get("ontology")

        if not project_id:
            return jsonify({"error": "project_id required"}), 400
        if not get_project(project_id):
            return jsonify({"error": f"project {project_id} not found"}), 404

        task_id = str(uuid.uuid4())
        save_task(task_id, {"task_id": task_id, "status": "queued", "project_id": project_id})

        t = threading.Thread(
            target=_run_build,
            args=(task_id, project_id, graph_name, ontology),
            daemon=True,
        )
        t.start()

        return jsonify({"task_id": task_id, "status": "queued"})
    except Exception as e:
        log.exception("graph_build failed")
        return jsonify({"error": str(e)}), 500


@bp.route("/build/status", methods=["GET"])
def graph_build_status():
    task_id = request.args.get("task_id")
    if not task_id:
        return jsonify({"error": "task_id required"}), 400
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404
    return jsonify(task)


# ---------------------------------------------------------------------------
# Graph read
# ---------------------------------------------------------------------------
@bp.route("/<graph_id>", methods=["GET"])
def graph_get(graph_id: str):
    g = get_graph(graph_id)
    if not g:
        return jsonify({"error": "graph not found"}), 404
    return jsonify(g)

