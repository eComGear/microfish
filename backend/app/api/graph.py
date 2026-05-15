# backend/app/api/graph.py
from __future__ import annotations
import threading, traceback, uuid, time
from flask import Blueprint, jsonify, request

from app.services.ontology_generator import OntologyGenerator
from app.services.graph_builder import GraphBuilderService
from app.services.text_processor import TextProcessor

graph_bp = Blueprint("graph", __name__)

# in-memory task + project store (swap for DB later)
_TASKS: dict[str, dict] = {}
_PROJECTS: dict[str, dict] = {}
_GRAPHS: dict[str, dict] = {}
_builder = GraphBuilderService()


def _ok(data, code=200):
    return jsonify({"success": True, "data": data}), code

def _err(msg, code=400):
    return jsonify({"success": False, "error": msg}), code


@graph_bp.route("/health", methods=["GET"])
def health():
    return _ok({"service": "graph", "status": "ok"})


@graph_bp.route("/ontology/generate", methods=["POST"])
def ontology_generate():
    """
    Multipart form:
      files[]                (optional, .txt/.md/.pdf)
      simulation_requirement (required)
      project_name           (optional)
      additional_context     (optional)
    """
    sim_req = (request.form.get("simulation_requirement") or "").strip()
    if not sim_req:
        return _err("simulation_requirement is required", 400)

    project_name = (request.form.get("project_name") or "MiroFish Project").strip()
    additional   = (request.form.get("additional_context") or "").strip()

    files = request.files.getlist("files")
    docs, file_meta, total_len = [], [], 0
    for f in files:
        try:
            raw = f.read() or b""
            text = raw.decode("utf-8", errors="ignore")
            docs.append(text)
            file_meta.append({"filename": f.filename, "size": len(raw)})
            total_len += len(text)
        except Exception as e:
            return _err(f"failed reading {f.filename}: {e}", 400)

    if additional:
        docs.append(additional)
        total_len += len(additional)

    try:
        gen = OntologyGenerator()
        ontology = gen.generate(
            document_texts=docs or [sim_req],
            simulation_requirement=sim_req,
        )
    except Exception as e:
        traceback.print_exc()
        return _err(f"ontology generation failed: {e}", 500)

    project_id = uuid.uuid4().hex
    _PROJECTS[project_id] = {
        "project_id": project_id,
        "project_name": project_name,
        "simulation_requirement": sim_req,
        "documents": docs,
        "ontology": ontology,
    }

    return _ok({
        "project_id": project_id,
        "project_name": project_name,
        "ontology": ontology,
        "analysis_summary": f"Generated ontology from {len(docs)} document(s).",
        "files": file_meta,
        "total_text_length": total_len,
    })


@graph_bp.route("/build", methods=["POST"])
def build():
    body = request.get_json(silent=True) or {}
    project_id = body.get("project_id")
    if not project_id or project_id not in _PROJECTS:
        return _err("unknown project_id", 404)

    proj = _PROJECTS[project_id]
    task_id = uuid.uuid4().hex
    _TASKS[task_id] = {"task_id": task_id, "status": "pending", "progress": 0}

    def run():
        try:
            _TASKS[task_id].update(status="processing", progress=5, message="creating graph")
            graph_id = _builder.create_graph(body.get("graph_name") or proj["project_name"])
            _builder.set_ontology(graph_id, proj["ontology"] or {})

            text = "\n\n".join(proj["documents"]) or proj["simulation_requirement"]
            chunks = TextProcessor.split_text(text, chunk_size=500, overlap=50)
            _TASKS[task_id].update(progress=15, message=f"ingesting {len(chunks)} chunks")
            _builder.add_text_batches(graph_id, chunks)
            _builder._wait_for_episodes(graph_id)

            data = _builder.get_graph_data(graph_id)
            _GRAPHS[graph_id] = data
            _TASKS[task_id].update(
                status="completed", progress=100,
                result={
                    "project_id": project_id,
                    "graph_id": graph_id,
                    "node_count": len(data.get("nodes", [])),
                    "edge_count": len(data.get("edges", [])),
                },
            )
        except Exception as e:
            traceback.print_exc()
            _TASKS[task_id].update(status="failed", error=str(e))

    threading.Thread(target=run, daemon=True).start()
    return _ok({"project_id": project_id, "task_id": task_id, "message": "build started"})


@graph_bp.route("/task/<task_id>", methods=["GET"])
def task(task_id):
    t = _TASKS.get(task_id)
    if not t:
        return _err("unknown task", 404)
    return _ok(t)


@graph_bp.route("/data/<graph_id>", methods=["GET"])
def graph_data(graph_id):
    data = _GRAPHS.get(graph_id) or _builder.get_graph_data(graph_id)
    if not data:
        return _err("graph not found", 404)
    return _ok(data)

