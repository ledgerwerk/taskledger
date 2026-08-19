from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast

from taskledger.errors import LaunchError
from taskledger.ids import (
    slugify_project_ref as _slugify,
)
from taskledger.storage.common import load_json_array as _load_json_array
from taskledger.storage.common import (
    relative_to_workspace as _relative_to_workspace,
)
from taskledger.storage.common import write_json as _write_json
from taskledger.storage.paths import ProjectPaths
from taskledger.timeutils import utc_now_iso

ProjectRepoKind = Literal["odoo", "enterprise", "custom", "shared", "generic"]


@dataclass(slots=True, frozen=True)
class ProjectRepo:
    name: str
    slug: str
    path: str
    kind: ProjectRepoKind
    branch: str | None
    notes: str | None
    created_at: str
    updated_at: str
    role: Literal["read", "write", "both"] = "read"
    preferred_for_execution: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "slug": self.slug,
            "path": self.path,
            "kind": self.kind,
            "branch": self.branch,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "role": self.role,
            "preferred_for_execution": self.preferred_for_execution,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectRepo:
        kind = _string_value(data, "kind")
        if kind not in {"odoo", "enterprise", "custom", "shared", "generic"}:
            raise ValueError(f"Unsupported project repo kind: {kind}")
        role = _optional_string_value(data, "role") or "read"
        if role not in {"read", "write", "both"}:
            raise ValueError(f"Unsupported project repo role: {role}")
        return cls(
            name=_string_value(data, "name"),
            slug=_string_value(data, "slug"),
            path=_string_value(data, "path"),
            kind=cast(ProjectRepoKind, kind),
            branch=_optional_string_value(data, "branch"),
            notes=_optional_string_value(data, "notes"),
            created_at=_string_value(data, "created_at"),
            updated_at=_string_value(data, "updated_at"),
            role=cast(Literal["read", "write", "both"], role),
            preferred_for_execution=bool(data.get("preferred_for_execution", False)),
        )


def load_repos(paths: ProjectPaths) -> list[ProjectRepo]:
    return [
        ProjectRepo.from_dict(item)
        for item in _load_json_array(paths.repo_index_path, "project repo index")
    ]


def save_repos(paths: ProjectPaths, repos: list[ProjectRepo]) -> None:
    _write_json(paths.repo_index_path, [item.to_dict() for item in repos])


def add_repo(
    paths: ProjectPaths,
    *,
    name: str,
    path: Path,
    kind: str = "generic",
    branch: str | None = None,
    notes: str | None = None,
    role: str = "read",
    preferred_for_execution: bool = False,
) -> ProjectRepo:
    if kind not in {"odoo", "enterprise", "custom", "shared", "generic"}:
        raise LaunchError(f"Unsupported project repo kind: {kind}")
    if role not in {"read", "write", "both"}:
        raise LaunchError(f"Unsupported project repo role: {role}")
    if preferred_for_execution and role == "read":
        raise LaunchError(
            "Read-only repos cannot be marked as the default execution repo."
        )
    repos = load_repos(paths)
    slug = _slugify(name)
    _ensure_unique_repo_identity(repos, name=name, slug=slug)
    repo_path = path.expanduser()
    if not repo_path.is_absolute():
        repo_path = paths.workspace_root / repo_path
    repo_path = repo_path.resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        raise LaunchError(f"Project repo path does not exist: {path}")
    now = utc_now_iso()
    repo = ProjectRepo(
        name=name,
        slug=slug,
        path=_relative_to_workspace(paths, repo_path),
        kind=cast(ProjectRepoKind, kind),
        branch=branch,
        notes=notes,
        created_at=now,
        updated_at=now,
        role=cast(Literal["read", "write", "both"], role),
        preferred_for_execution=preferred_for_execution,
    )
    repos.append(repo)
    repos.sort(key=lambda item: item.slug)
    save_repos(
        paths,
        _preferred_repo_state(repos, preferred_slug=repo.slug)
        if preferred_for_execution
        else repos,
    )
    return repo


def resolve_repo(paths: ProjectPaths, ref: str) -> ProjectRepo:
    repos = load_repos(paths)
    normalized_ref = _slugify(ref)
    candidates = [
        item
        for item in repos
        if item.name == ref or item.slug == ref or item.slug == normalized_ref
    ]
    if not candidates:
        raise LaunchError(f"Unknown project repo: {ref}")
    if len(candidates) > 1:
        raise LaunchError(f"Ambiguous project repo ref: {ref}")
    return candidates[0]


def resolve_repo_root(paths: ProjectPaths, ref: str) -> Path:
    repo = resolve_repo(paths, ref)
    candidate = Path(repo.path)
    if not candidate.is_absolute():
        candidate = paths.workspace_root / candidate
    candidate = candidate.resolve()
    if not candidate.exists() or not candidate.is_dir():
        raise LaunchError(f"Project repo path does not exist: {repo.path}")
    return candidate


def remove_repo(paths: ProjectPaths, ref: str) -> ProjectRepo:
    repos = load_repos(paths)
    repo = resolve_repo(paths, ref)
    remaining = [item for item in repos if item.slug != repo.slug]
    save_repos(paths, remaining)
    return repo


def set_repo_role(paths: ProjectPaths, ref: str, *, role: str) -> ProjectRepo:
    if role not in {"read", "write", "both"}:
        raise LaunchError(f"Unsupported project repo role: {role}")
    repos = load_repos(paths)
    repo = resolve_repo(paths, ref)
    if role == "read" and repo.preferred_for_execution:
        raise LaunchError(
            "Default execution repo cannot be changed to read-only. "
            "Set a different default first or clear the default execution repo."
        )
    updated = replace(
        repo,
        role=cast(Literal["read", "write", "both"], role),
        updated_at=utc_now_iso(),
    )
    for index, item in enumerate(repos):
        if item.slug == repo.slug:
            repos[index] = updated
            break
    save_repos(paths, repos)
    return updated


def set_default_execution_repo(paths: ProjectPaths, ref: str) -> ProjectRepo:
    repos = load_repos(paths)
    repo = resolve_repo(paths, ref)
    if repo.role == "read":
        raise LaunchError(
            f"Project repo {repo.name} is read-only and cannot be the default "
            "execution repo."
        )
    updated_repos = _preferred_repo_state(repos, preferred_slug=repo.slug)
    save_repos(paths, updated_repos)
    return next(item for item in updated_repos if item.slug == repo.slug)


def clear_default_execution_repo(paths: ProjectPaths) -> list[ProjectRepo]:
    repos = load_repos(paths)
    updated_repos = _preferred_repo_state(repos, preferred_slug=None)
    save_repos(paths, updated_repos)
    return updated_repos


def _ensure_unique_repo_identity(
    repos: list[ProjectRepo], *, name: str, slug: str
) -> None:
    for item in repos:
        if item.name == name:
            raise LaunchError(f"Project repo already exists with name: {name}")
        if item.slug == slug:
            raise LaunchError(f"Project repo already exists with slug: {slug}")


def _preferred_repo_state(
    repos: list[ProjectRepo], *, preferred_slug: str | None
) -> list[ProjectRepo]:
    changed = False
    updated: list[ProjectRepo] = []
    timestamp = utc_now_iso()
    for item in repos:
        preferred = item.slug == preferred_slug if preferred_slug is not None else False
        if item.preferred_for_execution == preferred:
            updated.append(item)
            continue
        updated.append(
            replace(
                item,
                preferred_for_execution=preferred,
                updated_at=timestamp,
            )
        )
        changed = True
    return updated if changed else repos


def _string_value(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing or invalid {key}")
    return value


def _optional_string_value(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Invalid {key}")  # noqa: TRY004
    return value
