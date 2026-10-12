"""Read original study guides through a repository-rooted, read-only facade.

These JSON documents are research learning resources, never question records or
grading keys.  Their citations are checked by the dataset contract tests; callers
must display ``notice`` and ``review`` alongside the explanatory material.
"""
from __future__ import annotations

import json
from typing import Optional

from services.knowledge.repository import KnowledgeRepository, get_repository


GUIDE_FILE = "数据集/教资/resources/study_guides.jsonl"
SCENARIO_FILE = "数据集/教资/resources/interview_scenarios.jsonl"


class LearningResources:
    """A small extension of KnowledgeRepository for non-question learning data.

    Read on each call so local edits are visible immediately and the returned
    dictionaries cannot mutate a shared cache. Missing data means an empty list;
    malformed data raises ValueError with its file and line, never a partial list
    that would conceal a damaged or duplicate record.
    """

    def __init__(self, repository: Optional[KnowledgeRepository] = None) -> None:
        self.repository = repository if repository is not None else get_repository()

    def _records(self, rel: str, key: str, kind: str) -> list[dict]:
        path = self.repository.path(rel)
        if not path.is_file():
            return []
        records: list[dict] = []
        seen: set[str] = set()
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                location = f"{rel}:{line_number}"
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{location}: invalid JSON") from exc
                if not isinstance(record, dict) or not isinstance(record.get(key), str) or not record[key]:
                    raise ValueError(f"{location}: {kind} requires a {key}")
                if record[key] in seen:
                    raise ValueError(f"{location}: duplicate {key} {record[key]}")
                seen.add(record[key])
                records.append(record)
        return records

    def list_guides(self, node_id: Optional[str] = None) -> list[dict]:
        guides = self._records(GUIDE_FILE, "node_id", "guide")
        if node_id is not None:
            guides = [guide for guide in guides if guide["node_id"] == node_id]
        return guides

    def get_guide(self, node_id: str) -> Optional[dict]:
        guides = self.list_guides(node_id)
        return guides[0] if guides else None

    def list_scenarios(self, exam: Optional[str] = None) -> list[dict]:
        """结构化问答题面的唯一来源：库内面试情境资源，按资源自带的 exam 标注过滤。"""
        scenarios = self._records(SCENARIO_FILE, "resource_id", "scenario")
        if exam is not None:
            scenarios = [row for row in scenarios if row.get("exam") == exam]
        return scenarios


def list_guides(node_id: Optional[str] = None) -> list[dict]:
    """Convenience entry point using the shared KnowledgeRepository."""
    return LearningResources().list_guides(node_id)


def get_guide(node_id: str) -> Optional[dict]:
    """Return one guide by its graph node ID, or None when absent."""
    return LearningResources().get_guide(node_id)
