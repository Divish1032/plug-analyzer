from __future__ import annotations

import json
import os
import socket
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from uuid import uuid4

import psutil

from plug_analyzer.models import FinalizedRun, SampleAnnotation, SourceMetadata

SCHEMA_VERSION = 3
PROJECT_SUFFIX = ".plug-project"


class ProjectError(RuntimeError):
    """Base project-storage error."""


class ProjectLockedError(ProjectError):
    """Raised when another live application instance owns the project."""


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def database(self) -> Path:
        return self.root / "project.sqlite"

    @property
    def lock(self) -> Path:
        return self.root / ".plug-analyzer.lock"

    @property
    def sources(self) -> Path:
        return self.root / "sources"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def work(self) -> Path:
        return self.root / "work"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def create_directories(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for path in (
            self.sources,
            self.data,
            self.runs,
            self.exports,
            self.work,
            self.logs,
        ):
            path.mkdir(exist_ok=True)


class ProjectStore:
    def __init__(self, root: Path, *, read_only: bool = False) -> None:
        self.paths = ProjectPaths(root.resolve())
        self.read_only = read_only
        self._connection: sqlite3.Connection | None = None
        self._owns_lock = False

    @classmethod
    def create(cls, root: Path, *, name: str) -> Self:
        if root.exists() and any(root.iterdir()):
            raise ProjectError("new project folder must be empty")
        store = cls(root)
        store.paths.create_directories()
        try:
            store._acquire_lock()
            store._connect()
            store._initialize_schema(name=name)
        except Exception:
            store.close()
            raise
        return store

    @classmethod
    def open(cls, root: Path, *, read_only: bool = False) -> Self:
        store = cls(root, read_only=read_only)
        if not store.paths.database.is_file():
            raise ProjectError(f"not a Plug Analyzer project: {root}")
        try:
            if not read_only:
                store._acquire_lock()
            store._connect()
            store._verify_schema()
        except Exception:
            store.close()
            raise
        return store

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise ProjectError("project is closed")
        return self._connection

    def _connect(self) -> None:
        if self.read_only:
            uri = f"file:{self.paths.database.as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
        else:
            connection = sqlite3.connect(self.paths.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        self._connection = connection

    def _initialize_schema(self, *, name: str) -> None:
        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE project (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL
                );
                CREATE TABLE samples (
                    sample_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    cache_path TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE runs (
                    run_id TEXT PRIMARY KEY,
                    sample_id TEXT NOT NULL REFERENCES samples(sample_id) ON DELETE RESTRICT,
                    protocol_id TEXT NOT NULL,
                    protocol_version TEXT NOT NULL,
                    algorithm_version TEXT NOT NULL,
                    run_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finalized_at TEXT NOT NULL
                );
                CREATE TABLE sample_annotations (
                    sample_id TEXT PRIMARY KEY REFERENCES samples(sample_id) ON DELETE CASCADE,
                    annotation_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX idx_runs_sample ON runs(sample_id, finalized_at);
                """
            )
            self.connection.execute(
                "INSERT INTO project VALUES (1, ?, ?, ?)",
                (name, datetime.now(UTC).isoformat(), SCHEMA_VERSION),
            )
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _verify_schema(self) -> None:
        row = self.connection.execute("PRAGMA user_version").fetchone()
        version = int(row[0])
        if version in {1, 2} and not self.read_only:
            self._migrate_to_v3(version)
            version = SCHEMA_VERSION
        if version not in ({1, 2, SCHEMA_VERSION} if self.read_only else {SCHEMA_VERSION}):
            raise ProjectError(
                f"unsupported project schema {version}; this app supports 1-{SCHEMA_VERSION}"
            )

    def _migrate_to_v3(self, version: int) -> None:
        """Keep old projects readable while moving to the simpler app-run schema."""

        with self.connection:
            if version == 1:
                self.connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sample_annotations (
                        sample_id TEXT PRIMARY KEY REFERENCES samples(sample_id) ON DELETE CASCADE,
                        annotation_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
            self.connection.execute(
                "UPDATE project SET schema_version = ? WHERE singleton = 1",
                (SCHEMA_VERSION,),
            )
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _acquire_lock(self) -> None:
        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "created_at": datetime.now(UTC).isoformat(),
        }
        for attempt in range(2):
            try:
                descriptor = os.open(
                    self.paths.lock,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError as error:
                if attempt == 0 and self._remove_stale_lock():
                    continue
                raise ProjectLockedError(self._lock_description()) from error
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True)
            self._owns_lock = True
            return
        raise ProjectLockedError("project is locked")

    def _remove_stale_lock(self) -> bool:
        try:
            payload = json.loads(self.paths.lock.read_text(encoding="utf-8"))
            same_host = payload.get("host") == socket.gethostname()
            pid = int(payload.get("pid"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False
        if same_host and not psutil.pid_exists(pid):
            self.paths.lock.unlink(missing_ok=True)
            return True
        return False

    def _lock_description(self) -> str:
        try:
            payload = json.loads(self.paths.lock.read_text(encoding="utf-8"))
            return f"project is already open by PID {payload.get('pid')} on {payload.get('host')}"
        except (OSError, json.JSONDecodeError):
            return "project is locked by another application instance"

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._owns_lock:
            self.paths.lock.unlink(missing_ok=True)
            self._owns_lock = False

    def project_info(self) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM project WHERE singleton = 1").fetchone()
        return dict(row)

    def add_sample(
        self,
        *,
        name: str,
        metadata: SourceMetadata,
        cache_path: str | None = None,
        sample_id: str | None = None,
    ) -> str:
        self._require_writable()
        identifier = sample_id or uuid4().hex
        if cache_path and (Path(cache_path).is_absolute() or ".." in Path(cache_path).parts):
            raise ProjectError("cache path must stay relative to the project")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO samples(
                    sample_id, name, source_path, source_sha256, metadata_json,
                    cache_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    name,
                    metadata.source_path,
                    metadata.source_sha256,
                    metadata.model_dump_json(),
                    cache_path,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return identifier

    def list_samples(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM samples ORDER BY created_at, sample_id"
        ).fetchall()
        return [dict(row) for row in rows]

    def sample_metadata(self, sample_id: str) -> SourceMetadata:
        row = self.connection.execute(
            "SELECT metadata_json FROM samples WHERE sample_id = ?", (sample_id,)
        ).fetchone()
        if row is None:
            raise KeyError(sample_id)
        return SourceMetadata.model_validate_json(row[0])

    def set_sample_cache(self, sample_id: str, cache_path: str | None) -> None:
        """Update only the rebuildable cache pointer for a known sample."""

        self._require_writable()
        if cache_path and (Path(cache_path).is_absolute() or ".." in Path(cache_path).parts):
            raise ProjectError("cache path must stay relative to the project")
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE samples SET cache_path = ? WHERE sample_id = ?",
                (cache_path, sample_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(sample_id)

    def save_finalized_run(self, run: FinalizedRun) -> None:
        self._require_writable()
        for relative in run.artifacts.values():
            if not (self.paths.root / relative).resolve().is_relative_to(self.paths.root):
                raise ProjectError("run artifact escapes project root")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO runs(
                    run_id, sample_id, protocol_id, protocol_version, algorithm_version,
                    run_json, created_at, finalized_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.sample_id,
                    run.protocol.protocol_id,
                    run.protocol.protocol_version,
                    run.protocol.algorithm_version,
                    run.model_dump_json(),
                    run.created_at.isoformat(),
                    run.finalized_at.isoformat(),
                ),
            )

    def list_runs(self, sample_id: str | None = None) -> list[FinalizedRun]:
        if sample_id is None:
            rows = self.connection.execute(
                "SELECT run_json FROM runs ORDER BY finalized_at, run_id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT run_json FROM runs WHERE sample_id = ? ORDER BY finalized_at, run_id",
                (sample_id,),
            ).fetchall()
        return [FinalizedRun.model_validate_json(row[0]) for row in rows]

    def set_sample_annotation(self, sample_id: str, annotation: SampleAnnotation) -> None:
        self._require_writable()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO sample_annotations(sample_id, annotation_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(sample_id) DO UPDATE SET
                    annotation_json = excluded.annotation_json,
                    updated_at = excluded.updated_at
                """,
                (sample_id, annotation.model_dump_json(), annotation.updated_at.isoformat()),
            )

    def sample_annotation(self, sample_id: str) -> SampleAnnotation:
        try:
            row = self.connection.execute(
                "SELECT annotation_json FROM sample_annotations WHERE sample_id = ?",
                (sample_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            # Read-only legacy schema v1 projects have no annotation table.
            return SampleAnnotation()
        return SampleAnnotation() if row is None else SampleAnnotation.model_validate_json(row[0])

    def delete_run(self, run_id: str) -> FinalizedRun:
        """Delete one saved run record; callers remove its verified artifact folder."""

        self._require_writable()
        row = self.connection.execute(
            "SELECT run_json FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        run = FinalizedRun.model_validate_json(row[0])
        with self.connection:
            self.connection.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        return run

    def checkpoint(self) -> None:
        """Flush SQLite state before a project is copied to another machine."""

        if self._connection is not None and not self.read_only:
            self.connection.commit()
            self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _require_writable(self) -> None:
        if self.read_only:
            raise ProjectError("project is open read-only")
