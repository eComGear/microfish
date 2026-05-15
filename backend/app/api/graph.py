import os
import uuid
import logging
import threading
from flask import Blueprint, request, jsonify

from app.store import (
    save_project, get_project,
    save_task, get_task,
    save_graph, get_graph,
)

logger = logging.getLogger(__name__)
graph_bp = Blueprint("graph", __name__)

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/data/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXT = {".txt", ".md", ".pdf"}

def _read_file(file_storage) -> str:
    name = (file_storage.filename or "").lower()
    ext = os.path.splitext(name)[1]
    if ext not in ALLOWED_EXT:
        return ""
    raw = file_storage.read()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(raw))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception as e:
            logger.warning("pdf parse failed for %s: %s", name, e)
            return ""
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""

@graph_bp.get("/health")
def health():
    return jsonify({"success": True, "data": {"status": "ok"}})

# ---------- POST /api/graph/ontology/generate (multipart) ----------
@graph_bp.post("/ontology/generate")
def ontology_generate():
    sim_req = (request.form.get("simulation_requirement") or "").strip()
    project_name = (request.form.get("project_name") or "MiroFish project").strip()
    extra = (request.form.get("additional_context") or "").strip()

    if not sim_req:
        return jsonify({"success": False, "error": "simulation_requirement is required"}), 400

    files = request.files.getlist("files") or request.files.getlist("files[]")
    docs = []
    file_meta = []
    for f in files:
        text = _read_file(f)
        if text:
            docs.append(text)
            file_meta.append({"filename": f.filename, "size": len(text)})
    if extra:
        docs.append(extra)

    try:
        from app.services.ontology_generator import OntologyGenerator
        gen = OntologyGenerator()
        result = gen.generate(document_texts=docs, simulation_requirement=sim_req)
        ontology = result.get("ontology") if isinstance(result, dict) else result
        summary = result.get("analysis_summary", "") if isinstance(result, dict) else ""
    except Exception as e:
        logger.exception("ontology generation failed")
        return jsonify({"success": False, "error": f"ontology generation failed: {e}"}), 500

    pid = str(uuid.uuid4())
    save_project(pid, {
        "name": project_name,
        "simulation_requirement": sim_req,
        "additional_context": extra,
        "documents": docs,
        "ontology": ontology,
        "analysis_summary": summary,
        "files": file_meta,
    })

    return jsonify({"success": True, "data": {
        "project_id": pid,
        "project_name": project_name,
        "ontology": ontology,
        "analysis_summary": summary,
        "files": file_meta,
        "total_text_length": sum(len(d) for d in docs),
    }})

# ---------- POST /api/graph/build ----------
def _run_build(task_id: str, project_id: str, graph_name: str):
    try:
        save_task(task_id, {"project_id": project_id, "status": "processing", "progress": 5,
                            "message": "loading project"})
        proj = get_project(project_id)
        if not proj:
            save_task(task_id, {"project_id": project_id, "status": "failed",
                                "error": "projectNotFound"})
            return

        from app.services.graph_builder_service import GraphBuilderService
        from app.services.text_processor import TextProcessor

        save_task(task_id, {"project_id": project_id, "status": "processing", "progress": 25,
                            "message": "splitting text"})
        chunks = []
        for d in proj.get("documents") or []:
            chunks.extend(TextProcessor.split_text(d))

        save_task(task_id, {"project_id": project_id, "status": "processing", "progress": 50,
                            "message": "building graph"})
        builder = GraphBuilderService()
        graph_data = builder.build_from_chunks(
            chunks=chunks,
            ontology=proj.get("ontology"),
            graph_name=graph_name,
        )

        gid = str(uuid.uuid4())
        nodes = graph_data.get("nodes") or []
        edges = graph_data.get("edges") or []
        save_graph(gid, {
            "project_id": project_id,
            "name": graph_name,
            "nodes": nodes,
            "edges": edges,
        })
        save_task(task_id, {
            "project_id": project_id,
            "status": "completed",
            "progress": 100,
            "result": {
                "project_id": project_id,
                "graph_id": gid,
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
        })
    except Exception as e:
        logger.exception("graph build failed")
        save_task(task_id, {"project_id": project_id, "status": "failed", "error": str(e)})

@graph_bp.post("/build")
def build():
    body = request.get_json(silent=True) or {}
    project_id = body.get("project_id")
    graph_name = body.get("graph_name") or "graph"
    if not project_id:
        return jsonify({"success": False, "error": "project_id is required"}), 400
    if not get_project(project_id):
        return jsonify({"success": False, "error": "projectNotFound"}), 404

    task_id = str(uuid.uuid4())
    save_task(task_id, {"project_id": project_id, "status": "pending", "progress": 0})
    threading.Thread(target=_run_build, args=(task_id, project_id, graph_name), daemon=True).start()
    return jsonify({"success": True, "data": {
        "project_id": project_id,
        "task_id": task_id,
        "message": "graph build started",
    }})

# ---------- GET /api/graph/task/<task_id> ----------
@graph_bp.get("/task/<task_id>")
def task_status(task_id: str):
    t = get_task(task_id)
    if not t:
        return jsonify({"success": False, "error": "taskNotFound"}), 404
    return jsonify({"success": True, "data": {"task_id": task_id, **t}})

# ---------- GET /api/graph/data/<graph_id> ----------
@graph_bp.get("/data/<graph_id>")
def graph_data(graph_id: str):
    g = get_graph(graph_id)
    if not g:
        return jsonify({"success": False, "error": "graphNotFound"}), 404
    return jsonify({"success": True, "data": {
        "graph_id": graph_id,
        "nodes": g.get("nodes") or [],
        "edges": g.get("edges") or [],
    }})


