# backend/app/graph_routes.py
import os
import uuid
import logging
import threading
import traceback
from typing import Any, Optional

from flask import Blueprint, request, jsonify

from .supabase_store import (
    get_extracted_text,
    upsert_project,
    get_project,
)

# 你的圖譜建構函式;名稱依實際情況調整
# 預期簽名: build_graph_from_text(text: str, ontology: dict | None, project_id: str) -> dict
from .graph_builder import build_graph_from_text

log = logging.getLogger(__name__)

bp = Blueprint("graph", __name__)

# ---------------------------------------------------------------------------
# In-memory task store
# 單機 Flask 夠用;多 worker 部署請改成 Redis / Supabase 表
# ---------------------------------------------------------------------------
_TASKS: dict[str, dict[str, Any]] = {}
_TASKS_LOCK = threading.Lock()


def _set_task(task_id: str, **fields) -> None:
    with _TASKS_LOCK:
        cur = _TASKS.get(task_id, {})
        cur.update(fields)
        _TASKS[task_id] = cur


def _get_task(task_id: str) -> Optional[dict[str, Any]]:
    with _TASKS_LOCK:
        return _TASKS.get(task_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _as_text(v) -> str:
    """把任何資料形狀安全轉成 str,避免 'list' object has no attribute 'strip'."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        parts = []
        for item in v:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("content") or item.get("text") or ""))
            else:
                parts.append(str(item))
        return "\n\n".join(p for p in parts if p)
    if isinstance(v, dict):
        return str(v.get("content") or v.get("text") or "")
    return str(v)


def _coerce_project_id(value) -> str:
    """前端有時把整個 project dict 傳進來,這裡取出 project_id."""
    if isinstance(value, dict):
        pid = value.get("project_id") or value.get("id")
        if not pid:
            raise ValueError("project_id missing in dict payload")
        return str(pid)
    if value is None:
        raise ValueError("project_id is required")
    return str(value)


# ---------------------------------------------------------------------------
# Build worker
# ---------------------------------------------------------------------------
def _run_build(task_id: str, project_id: str) -> None:
    try:
        log.info("[%s] 开始构建图谱...", task_id)
        _set_task(
            task_id,
            status="running",
            progress=5,
            message="loading extracted text",
            project_id=project_id,
        )

        # supabase_store.get_extracted_text 已改為回傳 str
        raw = get_extracted_text(project_id)
        text = _as_text(raw).strip()

        if not text:
            raise ValueError("no extracted text for project")

        _set_task(task_id, progress=20, message="building graph")

        project = get_project(project_id) or {}
        ontology = project.get("ontology")

        result = build_graph_from_text(text, ontology=ontology, project_id=project_id)

        graph_id = (
            result.get("graph_id")
            if isinstance(result, dict)
            else None
        ) or f"graph_{uuid.uuid4().hex[:12]}"

        # 把 graph_id 寫回 project
        try:
            upsert_project(
                {
                    "project_id": project_id,
                    "graph_id": graph_id,
                    "graph_build_task_id": task_id,
                }
            )
        except Exception as e:
            log.warning("[%s] upsert_project(graph_id) failed: %s", task_id, e)

        _set_task(
            task_id,
            status="succeeded",
            progress=100,
            message="done",
            graph_id=graph_id,
            result=result if isinstance(result, dict) else {"graph_id": graph_id},
        )
        log.info("[%s] 图谱构建完成 graph_id=%s", task_id, graph_id)

    except Exception as e:
        tb = traceback.format_exc()
        log.error("[%s] 图谱构建失败: %s\n%s", task_id, e, tb)
        _set_task(
            task_id,
            status="failed",
            progress=100,
            message="failed",
            error=str(e),
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@bp.post("/api/graph/build")
def graph_build():
    """啟動 async 圖譜建構,回傳 task_id."""
    payload = request.get_json(silent=True) or {}
    try:
        project_id = _coerce_project_id(
            payload.get("project_id") or payload.get("project") or payload
        )
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    proj = get_project(project_id)
    if not proj:
        return jsonify({"success": False, "error": "api.projectNotFound"}), 404

    task_id = str(uuid.uuid4())
    _set_task(
        task_id,
        status="pending",
        progress=0,
        message="queued",
        project_id=project_id,
        error=None,
    )

    t = threading.Thread(
        target=_run_build,
        args=(task_id, project_id),
        daemon=True,
    )
    t.start()

    return jsonify(
        {
            "success": True,
            "data": {"task_id": task_id, "project_id": project_id},
        }
    )


@bp.get("/api/graph/task/<task_id>")
def graph_task(task_id: str):
    """輪詢 task 狀態。找不到也回 JSON,不要讓 Flask 回 HTML 404。"""
    state = _get_task(task_id)
    if not state:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "task_not_found",
                    "data": {"task_id": task_id, "status": "unknown"},
                }
            ),
            404,
        )
    return jsonify({"success": True, "data": state})


@bp.get("/api/graph/data/<graph_id>")
def graph_data(graph_id: str):
    """讀取已建好的 graph。實際資料來源請接你現有的 store。"""
    try:
        # TODO: 換成你真正的 graph 取出邏輯
        from .graph_builder import load_graph  # 若沒有就改成你的實作
        data = load_graph(graph_id)
        if not data:
            return jsonify({"success": False, "error": "graph_not_found"}), 404
        return jsonify({"success": True, "data": data})
    except Exception as e:
        log.exception("graph_data failed")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Blueprint registration helper
# ---------------------------------------------------------------------------
def register(app) -> None:
    """在 create_app 裡呼叫: register(app)"""
    app.register_blueprint(bp)

