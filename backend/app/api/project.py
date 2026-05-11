from flask import Blueprint, request, jsonify
from . import project_bp  # 新增到 __init__.py
from ..models.project import ProjectManager

@project_bp.route('/create', methods=['POST'])
def create():
    data = request.get_json() or {}
    p = ProjectManager.create_project(name=data.get('name', 'guest'))
    return jsonify({"success": True, "project_id": p.project_id})

# 還要加 /upload 把檔案存進該 project
