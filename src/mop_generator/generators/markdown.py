"""Geração do MOP em Markdown."""

from __future__ import annotations

from typing import List

from ..models import MOP

PLACEHOLDER = "_A preencher_"


def _section(lines: List[str], title: str, level: int = 2) -> None:
    lines.append("")
    lines.append(f"{'#' * level} {title}")
    lines.append("")


def _paragraph(lines: List[str], text: str) -> None:
    lines.append(text if text else PLACEHOLDER)
    lines.append("")


def generate_markdown(mop: MOP) -> str:
    """Renderiza o MOP como uma string Markdown."""
    lines: List[str] = []

    # Título / Capa
    b = mop.branding
    cover_title = b.cover_title or mop.title
    lines.append(f"# {cover_title}")
    lines.append("")
    if b.project_title:
        lines.append(f"**Projeto:** {b.project_title}")
        lines.append("")
    if mop.subtitle:
        lines.append(f"_{mop.subtitle}_")
        lines.append("")

    # 1. Project Overview
    _section(lines, "1. Project Overview", level=2)

    # 1.1 Objetivo
    _section(lines, "1.1 Objetivo", level=3)
    _paragraph(lines, mop.objetivo)

    if mop.mudancas:
        lines.append("| Id | Ação | Descrição | Notas |")
        lines.append("| --- | --- | --- | --- |")
        for idx, ch in enumerate(mop.mudancas, start=1):
            notas = ch.notas.replace("|", "\\|")
            desc = ch.descricao.replace("|", "\\|")
            acao = ch.acao.replace("|", "\\|")
            lines.append(f"| {idx} | {acao} | {desc} | {notas} |")
        lines.append("")
    else:
        _paragraph(lines, PLACEHOLDER)

    # 1.2 Upgrade Plan
    _section(lines, "1.2 Upgrade Plan", level=3)
    schedule = mop.upgrade_schedule or PLACEHOLDER
    _paragraph(lines, f"**Upgrade Schedule:** {schedule}")

    # 1.3 Impacto
    _section(lines, "1.3 Impacto", level=3)
    if mop.impacto:
        for item in mop.impacto:
            lines.append(f"- {item}")
        lines.append("")
    else:
        _paragraph(lines, PLACEHOLDER)

    # 1.4 Plano de Backup
    _section(lines, "1.4 Plano de Backup", level=3)
    _paragraph(lines, mop.plano_backup)
    for pr in mop.pull_requests:
        lines.append(f"- {pr}")
    if mop.pull_requests:
        lines.append("")

    # 1.5 Validação Pós Implementação
    _section(lines, "1.5 Validação Pós Implementação", level=3)
    _paragraph(lines, mop.validacao)

    # 1.6 Plano de Volta (Rollback)
    _section(lines, "1.6 Plano de Volta (Rollback)", level=3)
    _paragraph(lines, mop.rollback)
    for pr in mop.pull_requests:
        lines.append(f"- {pr}")
    if mop.pull_requests:
        lines.append("")

    # 1.7 Execução
    _section(lines, "1.7 Execução", level=3)
    rt = mop.responsavel_tecnico
    lines.append("**Responsável Técnico (Quem vai executar)**")
    lines.append("")
    if rt.empresa:
        lines.append(f"- Empresa: {rt.empresa}")
    for p in rt.pessoas:
        lines.append(f"- {p.render()}")
    if not rt.empresa and not rt.pessoas:
        lines.append(f"- {PLACEHOLDER}")
    lines.append("")
    lines.append("**Equipe Day-After (Quem irá acompanhar o ambiente no dia posterior)**")
    lines.append("")
    da = mop.day_after
    if da.empresa:
        lines.append(f"- Empresa: {da.empresa}")
    if da.papel:
        lines.append(f"- Papel: {da.papel}")
    if not da.empresa and not da.papel:
        lines.append(f"- {PLACEHOLDER}")
    lines.append("")

    # 1.8 Acesso ao DevOps
    _section(lines, "1.8 Acesso ao DevOps", level=3)
    if mop.acesso_devops:
        _paragraph(lines, f"Necessário o acesso ao DevOps: {mop.acesso_devops}")
    else:
        _paragraph(lines, PLACEHOLDER)

    # 2. Alterações de API (somente se houver mudança de endpoints/payloads)
    if mop.api_changes:
        _section(lines, "2. Alterações de API (Endpoints e Payloads)", level=2)
        for ep in mop.api_changes:
            _section(lines, ep.title(), level=3)
            if ep.description:
                _paragraph(lines, ep.description)
            if ep.request_headers:
                lines.append("**Headers (request):**")
                lines.append("")
                for h in ep.request_headers:
                    lines.append(f"- `{h}`")
                lines.append("")
            if ep.request_body:
                lines.append("**Corpo da requisição (request):**")
                lines.append("")
                lines.append("```json")
                lines.append(ep.request_body)
                lines.append("```")
                lines.append("")
            resp_label = "**Resposta (response)"
            if ep.response_status:
                resp_label += f" — {ep.response_status}"
            resp_label += ":**"
            if ep.response_status or ep.response_headers or ep.response_body:
                lines.append(resp_label)
                lines.append("")
            for h in ep.response_headers:
                lines.append(f"- `{h}`")
            if ep.response_headers:
                lines.append("")
            if ep.response_body:
                lines.append("```json")
                lines.append(ep.response_body)
                lines.append("```")
                lines.append("")
            if ep.notes:
                _paragraph(lines, f"**Notas:** {ep.notes}")

    # Anexo: detalhes do Git
    if mop.git and (mop.git.commits or mop.git.changed_files):
        _section(lines, "Anexo A — Detalhes do Git", level=2)
        g = mop.git
        lines.append(f"- Repositório: {g.repo_url}")
        lines.append(f"- Branch: {g.branch}")
        if g.base:
            lines.append(f"- Base: {g.base}")
        lines.append("")

        if g.commits:
            lines.append(f"**Commits ({len(g.commits)}):**")
            lines.append("")
            for c in g.commits:
                lines.append(f"- `{c.short_sha}` {c.subject} — {c.author} ({c.date})")
            lines.append("")
        if g.changed_files:
            lines.append(f"**Arquivos alterados ({len(g.changed_files)}):**")
            lines.append("")
            for filepath in g.changed_files:
                lines.append(f"- `{filepath}`")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
