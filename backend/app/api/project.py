"""
Project API - 建立 / 查詢專案
"""

from flask import request, jsonify
from . import project_bp
from ..models.project import ProjectManager
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.project')


@project_bp.route('/create', methods=['POST'])
def create_project():
    """建立新專案,回傳 project_id"""
    try:
        data = request.get_json(silent=True) or {}
        name = data.get('name') or 'Untitled Project'

        project = ProjectManager.create_project(name=name)
        logger.info(f"已建立專案: {project.project_id}")

        return jsonify({
            'success': True,
            'project_id': project.project_id,
            'name': name,
        })
    except Exception as e:
        logger.exception("建立專案失敗")
        return jsonify({'success': False, 'error': str(e)}), 500


@project_bp.route('/<project_id>', methods=['GET'])
def get_project(project_id):
    """取得專案資訊"""
    try:
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({'success': False, 'error': 'projectNotFound'}), 404
        return jsonify({
            'success': True,
            'project_id': project.project_id,
        })
    except Exception as e:
        logger.exception("查詢專案失敗")
        return jsonify({'success': False, 'error': str(e)}), 500
