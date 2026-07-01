"""Fixtures compartilhadas dos testes."""

from __future__ import annotations

import subprocess

import pytest


def _git(args, cwd):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def git_repo(tmp_path):
    """Cria um repositório Git real com branch main e uma feature branch.

    Retorna (caminho_do_repo, nome_da_branch, base).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test User"], repo)
    _git(["config", "commit.gpgsign", "false"], repo)

    (repo / "app.py").write_text("print('base')\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-qm", "init: base app"], repo)

    _git(["checkout", "-q", "-b", "feature/registro"], repo)
    (repo / "pipeline.yaml").write_text("steps: []\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-qm", "feat: adiciona pipeline de correcao"], repo)

    (repo / "tasks.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-qm", "refactor: introduz TaskHelpers"], repo)

    return str(repo), "feature/registro", "main"
