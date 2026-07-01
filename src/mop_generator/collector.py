"""Preenchimento do MOP combinando dados do Git, config e prompts interativos."""

from __future__ import annotations

from typing import List, Optional

import click

from .git_utils import ssh_to_web_url
from .models import (
    Change,
    DayAfter,
    GitInfo,
    MOP,
    Person,
    ResponsavelTecnico,
)


class MissingFieldError(RuntimeError):
    """Campo obrigatório ausente em modo não interativo."""


def suggest_changes_from_git(git: GitInfo) -> List[Change]:
    """Sugere uma tabela de mudanças a partir dos assuntos dos commits."""
    changes: List[Change] = []
    for commit in git.commits:
        changes.append(
            Change(
                acao="Alteração",
                descricao=commit.subject,
                notas=f"{commit.short_sha} — {commit.author}",
            )
        )
    return changes


def _prompt_text(label: str, default: str, interactive: bool) -> str:
    if default:
        return default
    if not interactive:
        return ""
    return click.prompt(label, default="", show_default=False).strip()


def _prompt_bullets(label: str, existing: List[str], interactive: bool) -> List[str]:
    if existing:
        return existing
    if not interactive:
        return []
    click.echo(f"{label} (uma por linha, linha vazia para terminar):")
    bullets: List[str] = []
    while True:
        line = click.prompt("  -", default="", show_default=False).strip()
        if not line:
            break
        bullets.append(line)
    return bullets


def _prompt_changes(
    existing: List[Change], git: Optional[GitInfo], interactive: bool
) -> List[Change]:
    if existing:
        return existing
    if not interactive:
        # Sem config: cai para sugestão do git, se houver.
        return suggest_changes_from_git(git) if git else []

    if git and git.commits:
        if click.confirm(
            f"Gerar tabela de mudanças a partir dos {len(git.commits)} "
            f"commit(s) da branch?",
            default=True,
        ):
            return suggest_changes_from_git(git)

    click.echo("Informe as mudanças (linha vazia em 'Ação' para terminar):")
    changes: List[Change] = []
    while True:
        acao = click.prompt("  Ação", default="", show_default=False).strip()
        if not acao:
            break
        descricao = click.prompt("  Descrição").strip()
        notas = click.prompt("  Notas", default="", show_default=False).strip()
        changes.append(Change(acao=acao, descricao=descricao, notas=notas))
    return changes


def _prompt_pull_requests(existing: List[str], interactive: bool) -> List[str]:
    if existing:
        return existing
    if not interactive:
        return []
    click.echo("Links de Pull Request (uma URL por linha, vazio para terminar):")
    prs: List[str] = []
    while True:
        line = click.prompt("  PR", default="", show_default=False).strip()
        if not line:
            break
        prs.append(line)
    return prs


def _prompt_responsaveis(
    existing: ResponsavelTecnico, interactive: bool
) -> ResponsavelTecnico:
    if existing.pessoas:
        return existing
    if not interactive:
        return existing
    empresa = existing.empresa or click.prompt(
        "Empresa responsável técnica", default="", show_default=False
    ).strip()
    click.echo("Responsáveis técnicos (nome vazio para terminar):")
    pessoas: List[Person] = []
    while True:
        nome = click.prompt("  Nome", default="", show_default=False).strip()
        if not nome:
            break
        email = click.prompt("  Email", default="", show_default=False).strip()
        pessoas.append(Person(nome=nome, email=email))
    return ResponsavelTecnico(empresa=empresa, pessoas=pessoas)


def _prompt_day_after(existing: DayAfter, interactive: bool) -> DayAfter:
    if existing.empresa or existing.papel:
        return existing
    if not interactive:
        return existing
    empresa = click.prompt(
        "Equipe Day-After (empresa)", default="", show_default=False
    ).strip()
    papel = click.prompt(
        "Equipe Day-After (papel)", default="", show_default=False
    ).strip()
    return DayAfter(empresa=empresa, papel=papel)


def _derive_title(git: Optional[GitInfo]) -> str:
    """Deriva um título padrão a partir do nome do projeto/repositório."""
    if git:
        if git.project and git.project.name:
            return f"MOP Upgrade {git.project.name}"
        if git.repo_url:
            name = git.repo_url.rstrip("/").split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]
            if name:
                return f"MOP Upgrade {name}"
    return "MOP"


def pending_fields(mop: MOP) -> List[str]:
    """Lista os campos importantes que ficaram vazios (para aviso/pendências)."""
    pend: List[str] = []
    if not mop.objetivo:
        pend.append("Objetivo")
    if not mop.mudancas:
        pend.append("Tabela de mudanças")
    if not mop.upgrade_schedule:
        pend.append("Upgrade Schedule (janela)")
    if not mop.impacto:
        pend.append("Impacto")
    if not mop.plano_backup:
        pend.append("Plano de Backup")
    if not mop.validacao:
        pend.append("Validação Pós Implementação")
    if not mop.rollback:
        pend.append("Plano de Volta (Rollback)")
    if not mop.responsavel_tecnico.pessoas:
        pend.append("Responsável Técnico")
    if not (mop.day_after.empresa or mop.day_after.papel):
        pend.append("Equipe Day-After")
    if not mop.pull_requests:
        pend.append("Pull Requests")
    return pend


def build_mop(base_mop: MOP, git: Optional[GitInfo], interactive: bool) -> MOP:
    """Completa o MOP a partir do config (base_mop), do Git e de prompts.

    Em modo não interativo, campos ausentes não causam erro: ficam vazios e
    serão renderizados como "A preencher" no documento (veja pending_fields).
    """
    mop = base_mop
    mop.git = git

    # Título / subtítulo
    if not mop.title or mop.title == "MOP":
        typed = _prompt_text("Título do MOP", "", interactive)
        mop.title = typed or _derive_title(git)
    mop.subtitle = _prompt_text("Subtítulo", mop.subtitle, interactive)

    # Objetivo
    mop.objetivo = _prompt_text("Objetivo", mop.objetivo, interactive)

    # Mudanças
    mop.mudancas = _prompt_changes(mop.mudancas, git, interactive)

    # Janela de deploy
    mop.upgrade_schedule = _prompt_text(
        "Upgrade Schedule (janela de deploy)", mop.upgrade_schedule, interactive
    )

    # Impacto
    mop.impacto = _prompt_bullets("Impacto", mop.impacto, interactive)

    # Pull requests (usados em backup e rollback)
    mop.pull_requests = _prompt_pull_requests(mop.pull_requests, interactive)

    # Planos textuais
    mop.plano_backup = _prompt_text("Plano de Backup", mop.plano_backup, interactive)
    mop.validacao = _prompt_text(
        "Validação Pós Implementação", mop.validacao, interactive
    )
    mop.rollback = _prompt_text("Plano de Volta (Rollback)", mop.rollback, interactive)

    # Execução
    mop.responsavel_tecnico = _prompt_responsaveis(
        mop.responsavel_tecnico, interactive
    )
    mop.day_after = _prompt_day_after(mop.day_after, interactive)

    # Acesso ao DevOps: usa config, senão deriva do remote.
    if not mop.acesso_devops and git:
        mop.acesso_devops = ssh_to_web_url(git.remote_url) or git.remote_url
    if not mop.acesso_devops:
        mop.acesso_devops = _prompt_text(
            "Acesso ao DevOps (URL)", mop.acesso_devops, interactive
        )

    # Branding / capa: deriva título do projeto e da capa quando ausentes.
    _fill_branding(mop, git, interactive)

    return mop


def _project_name(git: Optional[GitInfo]) -> str:
    if git:
        if git.project and git.project.name:
            return git.project.name
        if git.repo_url:
            name = git.repo_url.rstrip("/").split("/")[-1]
            return name[:-4] if name.endswith(".git") else name
    return ""


def _fill_branding(mop: MOP, git: Optional[GitInfo], interactive: bool) -> None:
    b = mop.branding

    if not b.project_title:
        b.project_title = _prompt_text("Título do Projeto", "", interactive)
    if not b.project_title:
        b.project_title = _project_name(git)

    if not b.header_text:
        b.header_text = _prompt_text("Texto do cabeçalho", "", interactive)

    if not b.logo_path:
        b.logo_path = _prompt_text("Caminho da logo (imagem)", "", interactive)

    # Capa da modificação: usa a gerada pela LLM/config; senão, um fallback.
    if not b.cover_title:
        b.cover_title = _prompt_text("Capa da modificação", "", interactive)
    if not b.cover_title:
        nome = (b.project_title or _project_name(git) or "Projeto").upper()
        b.cover_title = f"MOP para Atualização das Funcionalidades em Produção – {nome}"
