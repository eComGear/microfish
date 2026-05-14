"""Graph API routes — ontology, build, status, data."""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import uuid
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from .. import supabase_store
from ..models.project import ProjectManager
from ..services.ontology_service import generate_ontology
from ..services.graph_service import build_graph

log = logging.getLogger(__name__)

graph_bp = Blueprint("graph", __name__, url_prefix="/api/graph")

# in-memory task registry; mirrored to supabase TASKS table
_TASKS: Dict[str, Dict[str, Any]] = {}
_TASKS_LOCK = threading.Lock()


def _set_task(task_id: str, **fields) -> Dict[str, Any]:
    with _TASKS_LOCK:
        state = _TASKS.setdefault(task_id, {"task_id": task_id})
        state.update(fields)
        snapshot = dict(state)
    try:
        supabase_store.save_task(task_id, snapshot)
    except Exception as e:
        log.warning("save_task failed for %s: %s", task_id, e)
    return snapshot


def _get_task(task_id: str) -> Dict[str, Any] | None:
    with _TASKS_LOCK:
        if task_id in _TASKS:
            return dict(_TASKS[task_id])
    try:
        return supabase_store.get_task(task_id)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/graph/ontology/generate  (multipart: files[] + project_name)
# ──────────────────────────────────────────────────────────────────────────────
@graph_bp.route("/ontology/generate", methods=["POST"])
def ontology_generate():
    try:
        project_name = (request.form.get("project_name") or "Untitled").strip()
        files = request.files.getlist("files") or []
        if not files:
            return jsonify(success=False, error="no files uploaded"), 400

        # persist source texts to supabase, build a project, run ontology
        project_id = str(uuid.uuid4())
        source_texts = []
        with tempfile.TemporaryDirectory() as tmp:
            for f in files:
                path = os.path.join(tmp, f.filename or f"file-{uuid.uuid4().hex}")
                f.save(path)
                with open(path, "rb") as fh:
                    raw = fh.read()
                try:
                    source_texts.append(raw.decode("utf-8", errors="ignore"))
                except Exception:
                    source_texts.append("")

        joined = "\n\n".join(t for t in source_texts if t)
        supabase_store.save_extracted_text(project_id, "uploads", joined)

        ontology = generate_ontology(joined, project_name=project_name)

        pm = ProjectManager()
        project = {
            "id": project_id,
            "name": project_name,
            "ontology": ontology,
            "source_count": len(files),
        }
        pm.save(project)

        return jsonify(success=True, data={
            "project_id": project_id,
            "project_name": project_name,
            "ontology": ontology,
        })
    except Exception as e:
        log.exception("ontology_generate failed")
        return jsonify(success=False, error=str(e)), 500


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/graph/build  { project_id, ontology }  → { task_id }
# ──────────────────────────────────────────────────────────────────────────────
@graph_bp.route("/build", methods=["POST"])
def graph_build():
    try:
        body = request.get_json(force=True) or {}
        project_id = body.get("project_id")
        ontology = body.get("ontology") or {}
        if not project_id:
            return jsonify(success=False, error="project_id required"), 400

        task_id = str(uuid.uuid4())
        _set_task(task_id, status="pending", progress=0, project_id=project_id)

        def _run():
            try:
                _set_task(task_id, status="running", progress=10)
                source_text = supabase_store.get_extracted_text(project_id, "uploads") or ""
                graph = build_graph(
                    source_text=source_text,
                    ontology=ontology,
                    on_progress=lambda p: _set_task(task_id, progress=int(p)),
                )
                # store graph in supabase under project_id
                supabase_store.save_graph(project_id, graph)
                _set_task(task_id, status="completed", progress=100, graph_id=project_id)
            except Exception as e:
                log.exception("graph build failed")
                _set_task(task_id, status="failed", error=str(e))

        threading.Thread(target=_run, daemon=True).start()
        return jsonify(success=True, data={"task_id": task_id})
    except Exception as e:
        log.exception("graph_build failed")
        return jsonify(success=False, error=str(e)), 500


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/graph/task/<task_id>
# ──────────────────────────────────────────────────────────────────────────────
@graph_bp.route("/task/<task_id>", methods=["GET"])
def graph_task(task_id: str):
    state = _get_task(task_id)
    if not state:
        return jsonify(success=False, error="task not found"), 404
    return jsonify(success=True, data=state)


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/graph/data/<graph_id>
# ──────────────────────────────────────────────────────────────────────────────
@graph_bp.route("/data/<graph_id>", methods=["GET"])
def graph_data(graph_id: str):
    try:
        graph = supabase_store.get_graph(graph_id)
        if not graph:
            return jsonify(success=False, error="graph not found"), 404
        return jsonify(success=True, data=graph)
    except Exception as e:
        log.exception("graph_data failed")
        return jsonify(success=False, error=str(e)), 500



