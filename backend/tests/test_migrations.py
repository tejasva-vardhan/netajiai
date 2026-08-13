"""Static safeguards for the production migration chain."""

from __future__ import annotations

import ast
from pathlib import Path


def test_alembic_revision_ids_fit_the_default_version_table() -> None:
    versions_dir = Path(__file__).parents[1] / "migrations" / "versions"
    revisions: list[str] = []
    for path in sorted(versions_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "revision"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                revisions.append(node.value.value)
                assert len(node.value.value) <= 32, (
                    f"{path.name} revision exceeds Alembic's 32-character "
                    "version-table limit"
                )
                break

    assert revisions
    assert len(revisions) == len(set(revisions))
