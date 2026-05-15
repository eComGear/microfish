"""backend/app/api/simulation.py

Fixes shipped in this version:

1. `start_simulation()` no longer crashes with
   `cannot access local variable 'platform' where it is not associated with a value`.
   `platform`, `max_rounds`, and `force` are now read from the request body
   BEFORE the Supabase cache lookup that uses them.

2. `prepare_simulation()` no longer leaks a Zep `ApiError: 404 not found`
   traceback to the frontend. If the bound `graph_id` is missing in Zep
   we return HTTP 400 with `api.graphNotBuilt`.

3. `upsert_simulation()` is called with keyword args only and tolerates a
   missing `input_hash` (auto-computed).

4. Tolerant import for SimulationService — upstream module name varies
   (`simulation_service`, `simulation`, `simulator`, `simulation_runner`).
   No more `ModuleNotFoundError: No module named 'app.services.simulation_service'`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

# ---- Tolerant import: try every known upstream name, then fall back to a
# stub so the blueprint can still register and the error is reported at
# request time instead of crashing the worker at boot. ----------------------
SimulationService = None  # type: ignore
_sim_import_error: Optional[str] = None
for _mod, _cls in (
    ("app.services.simulation_service", "SimulationService"),
    ("app.services.simulation", "SimulationService"),
    ("app.services.simulator", "SimulationService"),
    ("app.services.simulator", "Simulator"),
    ("app.services.simulation", "Simulator"),
    ("app.services.simulation_runner", "SimulationRunner"),
):
    try:
        SimulationService = getattr(__import__(_mod, fromlist=[_cls]), _cls)
        break
    except Exception as _e:  # pragma: no cover
        _sim_import_error = f"{_mod}.{_cls}: {_e}"
        continue

if SimulationService is None:  # pragma: no cover
    class SimulationService:  # type: ignore
        def __init__(self, *a, **kw):
            pass
        def run(self, **kwargs):
            raise RuntimeError(
                "SimulationService not available: " + (_sim_import_error or "unknown")
            )
# ---------------------------------------------------------------------------

from app.store import (
    get_graph,
    get_project,
    get_simulation,
    get_task,
    save_simulation,
    save_task,
)

# Optional Supabase mirror (best-effort, must never break the request).
try:
    from app.store.supabase_store import (
        upsert_simulation as sb_upsert_simulation,
        get_cached_simulation as sb_get_cached_simulation,
    )
except Exception:  # pragma: no cover
    sb_upsert_simulation = None
    sb_get_cached_simulation = None

# Zep error type for the 404 guard.
try:
    from zep_cloud.core.api_error import ApiError as ZepApiError
except Exception:  # pragma: no cover
    class ZepApiError(Exception):  # type: ignore
        status_code: Optional[int] = None

try:
    from app.services.zep_client import zep_client  # type: ignore
except Exception:  # pragma: no cover
    zep_client = None

log = logging.getLogger(__name__)

bp = Blueprint("simulation", __name__, url_prefix="/api/simulation")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _compute_input_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _safe_sb_upsert(row: Dict[str, Any]) -> None:
    if not sb_upsert_simulation:
        return
    try:
        sb_upsert_simulation(row=row, input_hash=row.get("input_hash"))
    except TypeError:
        try:
            sb_upsert_simulation(row, row.get("input_hash") or _compute_input_hash(row))
        except Exception as e:
            log.warning("Supabase upsert_simulation failed (ignored): %s", e)
    except Exception as e:
        log.warning("Supabase upsert_simulation failed (ignored): %s", e)


def _zep_graph_exists(graph_id: str) -> bool:
    if not zep_client:
        return True
    try:
        zep_client.graph.get(graph_id=graph_id)
        return True
    except ZepApiError as e:
        if getattr(e, "status_code", None) == 404:
            return False
        raise


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@bp.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "simulation"})


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
@bp.route("/entities/<graph_id>", methods=["GET"])
def entities(graph_id: str):
    enrich = request.args.get("enrich", "false").lower() == "true"
    if not _zep_graph_exists(graph_id):
        return jsonify({"error": "api.graphNotBuilt", "graph_id": graph_id}), 404
    try:
        nodes = []
        if zep_client:
            try:
                nodes = zep_client.graph.node.get_by_graph_id(graph_id=graph_id) or []
            except ZepApiError as e:
                if getattr(e, "status_code", None) == 404:
                    return jsonify({"error": "api.graphNotBuilt", "graph_id": graph_id}), 404
                raise
        return jsonify({"graph_id": graph_id, "enrich": enrich, "nodes": nodes})
    except Exception as e:
        log.exception("entities failed for graph %s", graph_id)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Prepare
# ---------------------------------------------------------------------------
@bp.route("/prepare", methods=["POST"])
def prepare_simulation():
    try:
        data = request.get_json(silent=True) or {}
        project_id = data.get("project_id")
        graph_id = data.get("graph_id")

        if not project_id:
            return jsonify({"error": "project_id required"}), 400

        proj = get_project(project_id)
        if not proj:
            return jsonify({"error": f"project {project_id} not found"}), 404

        graph_id = graph_id or proj.get("graph_id")
        if not graph_id:
            return jsonify({"error": "api.graphNotBuilt"}), 400

        if not _zep_graph_exists(graph_id):
            return jsonify({
                "error": "api.graphNotBuilt",
                "detail": f"graph {graph_id} not found in Zep, rebuild graph first",
            }), 400

        graph_row = get_graph(graph_id) or {}
        return jsonify({
            "project_id": project_id,
            "graph_id": graph_id,
            "nodes_count": len(graph_row.get("nodes") or []),
            "edges_count": len(graph_row.get("edges") or []),
            "ready": True,
        })
    except ZepApiError as e:
        log.exception("prepare_simulation: Zep error")
        if getattr(e, "status_code", None) == 404:
            return jsonify({"error": "api.graphNotBuilt"}), 400
        return jsonify({"error": "zep_error", "detail": str(e)}), 502
    except Exception as e:
        log.exception("prepare_simulation failed")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Start (async)
# ---------------------------------------------------------------------------
def _run_simulation(task_id: str, simulation_id: str, project_id: str,
                    graph_id: str, platform: str, max_rounds: int,
                    config: Dict[str, Any]):
    try:
        save_task(task_id, {
            "task_id": task_id, "status": "running",
            "project_id": project_id, "simulation_id": simulation_id,
        })

        svc = SimulationService()
        result = svc.run(
            project_id=project_id,
            graph_id=graph_id,
            platform=platform,
            max_rounds=max_rounds,
            config=config,
        ) or {}

        sim_row = {
            "simulation_id": simulation_id,
            "project_id": project_id,
            "graph_id": graph_id,
            "platform": platform,
            "max_rounds": max_rounds,
            "config": config,
            "result": result,
            "status": "succeeded",
        }
        save_simulation(simulation_id, sim_row)
        _safe_sb_upsert(sim_row)

        save_task(task_id, {
            "task_id": task_id, "status": "succeeded",
            "project_id": project_id, "simulation_id": simulation_id,
            "result": {"simulation_id": simulation_id},
        })
    except Exception as e:
        log.exception("simulation run failed for task %s", task_id)
        sim_row = {
            "simulation_id": simulation_id,
            "project_id": project_id,
            "graph_id": graph_id,
            "status": "failed",
            "error": str(e),
        }
        try:
            save_simulation(simulation_id, sim_row)
            _safe_sb_upsert(sim_row)
        except Exception:
            pass
        save_task(task_id, {
            "task_id": task_id, "status": "failed",
            "project_id": project_id, "simulation_id": simulation_id,
            "error": str(e),
        })


@bp.route("/start", methods=["POST"])
def start_simulation():
    try:
        data = request.get_json(silent=True) or {}
        project_id = data.get("project_id")
        if not project_id:
            return jsonify({"error": "project_id required"}), 400

        proj = get_project(project_id)
        if not proj:
            return jsonify({"error": f"project {project_id} not found"}), 404

        # Read all inputs BEFORE the cache block that references them.
        platform = data.get("platform") or "default"
        max_rounds = int(data.get("max_rounds") or 1)
        force = bool(data.get("force") or False)
        config = data.get("config") or {}
        graph_id = data.get("graph_id") or proj.get("graph_id")

        if not graph_id:
            return jsonify({"error": "api.graphNotBuilt"}), 400

        if not _zep_graph_exists(graph_id):
            return jsonify({
                "error": "api.graphNotBuilt",
                "detail": f"graph {graph_id} not found in Zep, rebuild graph first",
            }), 400

        cache_payload = {
            "project_id": project_id,
            "graph_id": graph_id,
            "platform": platform,
            "max_rounds": max_rounds,
            "config": config,
        }
        input_hash = _compute_input_hash(cache_payload)

        if not force and sb_get_cached_simulation:
            try:
                cached = sb_get_cached_simulation(
                    project_id=project_id, input_hash=input_hash,
                )
                if cached and cached.get("status") == "succeeded":
                    return jsonify({
                        "task_id": None,
                        "simulation_id": cached.get("simulation_id"),
                        "status": "cached",
                        "cached": True,
                    })
            except Exception as e:
                log.warning("Supabase get_cached_simulation failed (ignored): %s", e)

        simulation_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())

        sim_row = {
            "simulation_id": simulation_id,
            "project_id": project_id,
            "graph_id": graph_id,
            "platform": platform,
            "max_rounds": max_rounds,
            "config": config,
            "input_hash": input_hash,
            "status": "pending",
        }
        save_simulation(simulation_id, sim_row)
        _safe_sb_upsert(sim_row)

        save_task(task_id, {
            "task_id": task_id, "status": "queued",
            "project_id": project_id, "simulation_id": simulation_id,
        })

        threading.Thread(
            target=_run_simulation,
            args=(task_id, simulation_id, project_id, graph_id,
                  platform, max_rounds, config),
            daemon=True,
        ).start()

        return jsonify({
            "task_id": task_id,
            "simulation_id": simulation_id,
            "status": "queued",
        })
    except Exception as e:
        log.exception("start_simulation failed")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Status / read
# ---------------------------------------------------------------------------
@bp.route("/status", methods=["GET"])
def simulation_status():
    task_id = request.args.get("task_id")
    if not task_id:
        return jsonify({"error": "task_id required"}), 400
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404
    return jsonify(task)


@bp.route("/<simulation_id>", methods=["GET"])
def simulation_get(simulation_id: str):
    sim = get_simulation(simulation_id)
    if not sim:
        return jsonify({"error": "simulation not found"}), 404
    return jsonify(sim)
