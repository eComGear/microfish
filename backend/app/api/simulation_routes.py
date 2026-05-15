# backend/app/api/simulation_routes.py
"""
Simulation API routes.

Endpoints:
  POST /api/simulation/create        -> create a simulation row
  POST /api/simulation/prepare       -> generate agent profiles + sim config
  POST /api/simulation/start         -> start runner (cache-aware via Supabase)
  GET  /api/simulation/<sim_id>      -> simulation status
  GET  /api/simulation/logs          -> tailing log lines
  GET  /api/simulation/<sim_id>/timeline
  GET  /api/simulation/<sim_id>/posts
  GET  /api/simulation/<sim_id>/profiles
  POST /api/simulation/interview
  GET  /api/simulation/list?project_id=...   -> cached simulation history
"""

from __future__ import annotations

import logging
import threading
import traceback
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from app.services.simulation_service import (
    create_simulation,
    get_simulation,
    get_simulation_logs,
    get_simulation_posts,
    get_simulation_profiles,
    get_simulation_timeline,
    interview_agent,
    prepare_simulation,
    start_simulation_runner,
)
from app.services.supabase_store import (
    compute_input_hash,
    get_cached_simulation,
    list_simulations,
    upsert_simulation,
)

log = logging.getLogger(__name__)

simulation_bp = Blueprint("simulation", __name__, url_prefix="/api/simulation")


def _ok(data: Any, **extra) -> Any:
    payload = {"success": True, "data": data}
    payload.update(extra)
    return jsonify(payload)


def _err(message: str, status: int = 400, **extra) -> Any:
    payload = {"success": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------
@simulation_bp.route("/create", methods=["POST"])
def create():
    body = request.get_json(silent=True) or {}
    project_id = body.get("project_id")
    if not project_id:
        return _err("project_id is required", 400)
    try:
        sim = create_simulation(
            project_id=project_id,
            graph_id=body.get("graph_id"),
            enable_twitter=bool(body.get("enable_twitter", True)),
            enable_reddit=bool(body.get("enable_reddit", False)),
        )
        return _ok(sim)
    except Exception as e:  # noqa: BLE001
        log.exception("create simulation failed")
        return _err(str(e), 500)


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------
@simulation_bp.route("/prepare", methods=["POST"])
def prepare():
    body = request.get_json(silent=True) or {}
    sim_id = body.get("simulation_id")
    if not sim_id:
        return _err("simulation_id is required", 400)
    try:
        result = prepare_simulation(
            simulation_id=sim_id,
            max_agents=int(body.get("max_agents") or 10),
            use_llm_for_profiles=bool(body.get("use_llm_for_profiles", True)),
            parallel_profile_count=int(body.get("parallel_profile_count") or 4),
            force_regenerate=bool(body.get("force_regenerate", False)),
            seed_experts=body.get("seed_experts") or [],
        )
        return _ok(result)
    except Exception as e:  # noqa: BLE001
        log.exception("prepare simulation failed")
        return _err(str(e), 500)


# ---------------------------------------------------------------------------
# start  (cache-aware)
# ---------------------------------------------------------------------------
@simulation_bp.route("/start", methods=["POST"])
def start():
    body = request.get_json(silent=True) or {}
    sim_id: Optional[str] = body.get("simulation_id")
    if not sim_id:
        return _err("simulation_id is required", 400)

    # Accept both legacy and current field names from the frontend.
    num_agents = int(body.get("num_agents") or body.get("max_agents") or 10)
    num_rounds = int(body.get("num_rounds") or body.get("max_rounds") or 5)

    # --- Resolve project_id from the simulation row -------------------------
    try:
        sim_row = get_simulation(sim_id) or {}
    except Exception as e:  # noqa: BLE001
        log.exception("failed to load simulation %s", sim_id)
        return _err(f"failed to load simulation: {e}", 500)

    project_id = sim_row.get("project_id")
    graph_id = sim_row.get("graph_id")
    if not project_id:
        return _err("simulation has no project_id", 400)

    # --- Cache lookup -------------------------------------------------------
    config: Dict[str, Any] = {
        "project_id": project_id,
        "graph_id": graph_id,
        "num_agents": num_agents,
        "num_rounds": num_rounds,
        "enable_twitter": bool(sim_row.get("enable_twitter", True)),
        "enable_reddit": bool(sim_row.get("enable_reddit", False)),
    }
    input_hash = compute_input_hash(config)

    try:
        cached = get_cached_simulation(project_id=project_id, input_hash=input_hash)
    except Exception:  # noqa: BLE001
        log.exception("cache lookup failed (continuing without cache)")
        cached = None

    if cached and cached.get("status") == "completed" and cached.get("result"):
        log.info("simulation cache HIT project=%s hash=%s", project_id, input_hash)
        return _ok(
            {
                "task_id": cached.get("task_id") or f"cached:{cached['id']}",
                "cached": True,
                "simulation_id": sim_id,
                "result": cached["result"],
            }
        )

    # --- Mark running in cache, then kick off runner ------------------------
    try:
        upsert_simulation(
            project_id=project_id,
            input_hash=input_hash,
            config=config,
            status="running",
            simulation_id=sim_id,
        )
    except Exception:  # noqa: BLE001
        log.exception("cache upsert (running) failed (continuing)")

    try:
        task = start_simulation_runner(
            simulation_id=sim_id,
            num_agents=num_agents,
            num_rounds=num_rounds,
        )
        task_id = task.get("task_id") if isinstance(task, dict) else str(task)

        # Persist final result asynchronously when runner finishes.
        def _finalize() -> None:
            try:
                from app.services.simulation_service import wait_for_simulation_result

                final = wait_for_simulation_result(sim_id)
                upsert_simulation(
                    project_id=project_id,
                    input_hash=input_hash,
                    config=config,
                    status="completed",
                    simulation_id=sim_id,
                    task_id=task_id,
                    result=final,
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("finalize cache failed: %s", exc)
                try:
                    upsert_simulation(
                        project_id=project_id,
                        input_hash=input_hash,
                        config=config,
                        status="failed",
                        simulation_id=sim_id,
                        task_id=task_id,
                        error=str(exc),
                    )
                except Exception:  # noqa: BLE001
                    log.exception("failed to record cache failure")

        threading.Thread(target=_finalize, name=f"sim-finalize-{sim_id}", daemon=True).start()

        return _ok({"task_id": task_id, "cached": False, "simulation_id": sim_id})
    except Exception as e:  # noqa: BLE001
        log.exception("start simulation failed")
        try:
            upsert_simulation(
                project_id=project_id,
                input_hash=input_hash,
                config=config,
                status="failed",
                simulation_id=sim_id,
                error=str(e),
            )
        except Exception:  # noqa: BLE001
            log.exception("cache upsert (failed) failed")
        return _err(str(e), 500, trace=traceback.format_exc())


# ---------------------------------------------------------------------------
# list cached simulations
# ---------------------------------------------------------------------------
@simulation_bp.route("/list", methods=["GET"])
def list_cached():
    project_id = request.args.get("project_id")
    if not project_id:
        return _err("project_id is required", 400)
    try:
        rows = list_simulations(project_id=project_id, limit=int(request.args.get("limit") or 50))
        return _ok({"count": len(rows), "simulations": rows})
    except Exception as e:  # noqa: BLE001
        log.exception("list simulations failed")
        return _err(str(e), 500)


# ---------------------------------------------------------------------------
# status / logs / timeline / posts / profiles / interview
# ---------------------------------------------------------------------------
@simulation_bp.route("/<sim_id>", methods=["GET"])
def status(sim_id: str):
    try:
        sim = get_simulation(sim_id)
        if not sim:
            return _err("simulation not found", 404)
        return _ok(sim)
    except Exception as e:  # noqa: BLE001
        log.exception("get simulation failed")
        return _err(str(e), 500)


@simulation_bp.route("/logs", methods=["GET"])
def logs():
    sim_id = request.args.get("simulation_id")
    if not sim_id:
        return _err("simulation_id is required", 400)
    from_line = int(request.args.get("from_line") or 0)
    try:
        lines, next_line = get_simulation_logs(sim_id, from_line=from_line)
        return _ok({"lines": lines, "next_line": next_line})
    except Exception as e:  # noqa: BLE001
        log.exception("get logs failed")
        return _err(str(e), 500)


@simulation_bp.route("/<sim_id>/timeline", methods=["GET"])
def timeline(sim_id: str):
    try:
        tl = get_simulation_timeline(sim_id)
        return _ok({"rounds_count": len(tl), "timeline": tl})
    except Exception as e:  # noqa: BLE001
        log.exception("timeline failed")
        return _err(str(e), 500)


@simulation_bp.route("/<sim_id>/posts", methods=["GET"])
def posts(sim_id: str):
    try:
        ps = get_simulation_posts(sim_id)
        return _ok({"count": len(ps), "posts": ps})
    except Exception as e:  # noqa: BLE001
        log.exception("posts failed")
        return _err(str(e), 500)


@simulation_bp.route("/<sim_id>/profiles", methods=["GET"])
def profiles(sim_id: str):
    try:
        pr = get_simulation_profiles(sim_id)
        return _ok({"count": len(pr), "profiles": pr})
    except Exception as e:  # noqa: BLE001
        log.exception("profiles failed")
        return _err(str(e), 500)


@simulation_bp.route("/interview", methods=["POST"])
def interview():
    body = request.get_json(silent=True) or {}
    sim_id = body.get("simulation_id")
    agent_id = body.get("agent_id")
    prompt = body.get("prompt")
    if not (sim_id and agent_id is not None and prompt):
        return _err("simulation_id, agent_id, prompt required", 400)
    try:
        result = interview_agent(simulation_id=sim_id, agent_id=int(agent_id), prompt=prompt)
        return _ok(result)
    except Exception as e:  # noqa: BLE001
        log.exception("interview failed")
        return _err(str(e), 500)
