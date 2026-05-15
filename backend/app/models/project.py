"""
项目上下文管理
Supabase is the source of truth so any Fly machine can serve any request.
Local disk is used only as a transient cache for uploaded raw files
(needed during ontology generation on the same request).
"""

import os
import uuid
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass, field

from ..config import Config
from .. import supabase_store


class ProjectStatus(str, Enum):
    CREATED = "created"
    ONTOLOGY_GENERATED = "ontology_generated"
    GRAPH_BUILDING = "graph_building"
    GRAPH_COMPLETED = "graph_completed"
    FAILED = "failed"


@dataclass
class Project:
    project_id: str
    name: str
    status: ProjectStatus
    created_at: str
    updated_at: str

    files: List[Dict[str, str]] = field(default_factory=list)
    total_text_length: int = 0

    ontology: Optional[Dict[str, Any]] = None
    analysis_summary: Optional[str] = None

    graph_id: Optional[str] = None
    graph_build_task_id: Optional[str] = None

    simulation_requirement: Optional[str] = None
    chunk_size: int = 500
    chunk_overlap: int = 50

    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status.value if isinstance(self.status, ProjectStatus) else self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "files": self.files,
            "total_text_length": self.total_text_length,
            "ontology": self.ontology,
            "analysis_summary": self.analysis_summary,
            "graph_id": self.graph_id,
            "graph_build_task_id": self.graph_build_task_id,
            "simulation_requirement": self.simulation_requirement,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Project':
        status = data.get('status', 'created')
        if isinstance(status, str):
            try:
                status = ProjectStatus(status)
            except ValueError:
                status = ProjectStatus.CREATED

        return cls(
            project_id=data['project_id'],
            name=data.get('name', 'Unnamed Project'),
            status=status,
            created_at=str(data.get('created_at') or ''),
            updated_at=str(data.get('updated_at') or ''),
            files=data.get('files') or [],
            total_text_length=data.get('total_text_length', 0) or 0,
            ontology=data.get('ontology'),
            analysis_summary=data.get('analysis_summary'),
            graph_id=data.get('graph_id'),
            graph_build_task_id=data.get('graph_build_task_id'),
            simulation_requirement=data.get('simulation_requirement'),
            chunk_size=data.get('chunk_size', 500) or 500,
            chunk_overlap=data.get('chunk_overlap', 50) or 50,
            error=data.get('error'),
        )


class ProjectManager:
    """Project manager — Supabase-backed, machine-agnostic."""

    PROJECTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'projects')

    # ---------- local-disk helpers (raw uploads only) ----------

    @classmethod
    def _ensure_projects_dir(cls):
        os.makedirs(cls.PROJECTS_DIR, exist_ok=True)

    @classmethod
    def _get_project_dir(cls, project_id: str) -> str:
        return os.path.join(cls.PROJECTS_DIR, project_id)

    @classmethod
    def _get_project_files_dir(cls, project_id: str) -> str:
        return os.path.join(cls._get_project_dir(project_id), 'files')

    # ---------- CRUD (Supabase = source of truth) ----------

    @classmethod
    def create_project(cls, name: str = "Unnamed Project") -> Project:
        cls._ensure_projects_dir()
        project_id = f"proj_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()

        project = Project(
            project_id=project_id,
            name=name,
            status=ProjectStatus.CREATED,
            created_at=now,
            updated_at=now,
        )

        # local dirs for raw uploads on this machine
        os.makedirs(cls._get_project_files_dir(project_id), exist_ok=True)

        cls.save_project(project)
        return project

    @classmethod
    def save_project(cls, project: Project) -> None:
        project.updated_at = datetime.now().isoformat()
        supabase_store.upsert_project(project.to_dict())

    @classmethod
    def get_project(cls, project_id: str) -> Optional[Project]:
        data = supabase_store.get_project(project_id)
        if not data:
            return None
        return Project.from_dict(data)

    @classmethod
    def list_projects(cls, limit: int = 50) -> List[Project]:
        rows = supabase_store.list_projects(limit=limit)
        return [Project.from_dict(r) for r in rows]

    @classmethod
    def delete_project(cls, project_id: str) -> bool:
        ok = supabase_store.delete_project(project_id)
        # best-effort local cleanup
        project_dir = cls._get_project_dir(project_id)
        if os.path.exists(project_dir):
            try:
                shutil.rmtree(project_dir)
            except Exception:  # noqa: BLE001
                pass
        return ok

    # ---------- file handling ----------

    @classmethod
    def save_file_to_project(cls, project_id: str, file_storage, original_filename: str) -> Dict[str, Any]:
        """Raw uploads are saved on the local disk of the machine that received them.
        That's fine because file extraction happens in the same request."""
        files_dir = cls._get_project_files_dir(project_id)
        os.makedirs(files_dir, exist_ok=True)

        ext = os.path.splitext(original_filename)[1].lower()
        safe_filename = f"{uuid.uuid4().hex[:8]}{ext}"
        file_path = os.path.join(files_dir, safe_filename)

        file_storage.save(file_path)
        file_size = os.path.getsize(file_path)

        return {
            "original_filename": original_filename,
            "saved_filename": safe_filename,
            "path": file_path,
            "size": file_size,
        }

    @classmethod
    def save_extracted_text(cls, project_id: str, text: str) -> None:
        """Extracted text MUST live in Supabase so /build on any machine can read it."""
        supabase_store.save_extracted_text(project_id, text)

    @classmethod
    def get_extracted_text(cls, project_id: str) -> Optional[str]:
        return supabase_store.get_extracted_text(project_id)

    @classmethod
    def get_project_files(cls, project_id: str) -> List[str]:
        files_dir = cls._get_project_files_dir(project_id)
        if not os.path.exists(files_dir):
            return []
        return [
            os.path.join(files_dir, f)
            for f in os.listdir(files_dir)
            if os.path.isfile(os.path.join(files_dir, f))
        ]

