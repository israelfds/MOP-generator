"""Núcleo de geração do MOP, reutilizável por CLI e UI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .collector import build_mop, pending_fields
from .config import load_config, mop_from_config
from .generators import generate_docx, generate_markdown
from .git_utils import collect_git_info, prepare_repo
from .llm import apply_llm_fields, generate_mop_fields, load_llm_config
from .models import MOP


@dataclass
class GenerationResult:
    """Resultado de uma geração de MOP."""

    output_path: str
    mop: MOP
    pending: List[str] = field(default_factory=list)
    used_llm: bool = False
    messages: List[str] = field(default_factory=list)


def default_output(fmt: str, repo: str, branch: str) -> str:
    """Gera um nome de arquivo de saída padrão."""
    base = os.path.basename(repo.rstrip("/"))
    if base.endswith(".git"):
        base = base[:-4]
    if not base:
        base = "mop"
    safe_branch = branch.replace("/", "-")
    ext = "docx" if fmt == "docx" else "md"
    return f"MOP_{base}_{safe_branch}.{ext}"


def generate_mop(
    repo: str,
    branch: str,
    base: Optional[str] = None,
    fmt: str = "docx",
    config_path: Optional[str] = None,
    output: Optional[str] = None,
    interactive: bool = False,
    use_llm: Optional[bool] = None,
    model: Optional[str] = None,
    llm_context: str = "",
    skip_git: bool = False,
    logo_path: Optional[str] = None,
    project_title: Optional[str] = None,
    cover_title: Optional[str] = None,
    header_text: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
) -> GenerationResult:
    """Executa o pipeline completo de geração do MOP.

    `use_llm=None` significa "usar o LLM se OPENROUTER_API_KEY existir".
    `log` é um callback opcional para reportar progresso (usado pela UI).
    Levanta ValueError para erros de uso e GitError/LLMError para falhas
    de infraestrutura (o chamador decide como exibir).
    """
    messages: List[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        if log:
            log(msg)

    # 1. Config opcional
    if config_path:
        base_mop = mop_from_config(load_config(config_path))
    else:
        base_mop = MOP()

    # Branding informado diretamente (UI/CLI) tem prioridade sobre o config.
    if logo_path:
        base_mop.branding.logo_path = logo_path
    if project_title:
        base_mop.branding.project_title = project_title
    if cover_title:
        base_mop.branding.cover_title = cover_title
    if header_text:
        base_mop.branding.header_text = header_text

    # 2. Git
    git_info = None
    if not skip_git:
        _log(f"Acessando repositório '{repo}' (branch '{branch}')...")
        with prepare_repo(repo, branch) as path:
            git_info = collect_git_info(path, repo, branch, base)
        _log(
            f"{len(git_info.commits)} commit(s), "
            f"{len(git_info.changed_files)} arquivo(s) alterado(s)."
        )

    # 3. LLM
    llm_cfg = load_llm_config(model)
    should_use_llm = use_llm if use_llm is not None else llm_cfg.configured
    used_llm = False
    if should_use_llm:
        if not llm_cfg.configured:
            raise ValueError(
                "Uso do LLM solicitado, mas OPENROUTER_API_KEY não está definida "
                "(configure no .env)."
            )
        if git_info is None:
            raise ValueError("O uso do LLM requer dados do Git (skip_git=False).")
        _log(f"Gerando conteúdo com LLM ({llm_cfg.model})...")
        fields = generate_mop_fields(llm_cfg, git_info, llm_context)
        base_mop = apply_llm_fields(base_mop, fields)
        used_llm = True
        _log("Conteúdo do LLM aplicado.")

    # 4. Completa (config + git + llm + prompts)
    mop = build_mop(base_mop, git_info, interactive)
    pending = pending_fields(mop)

    # 5. Saída
    if not output:
        output = default_output(fmt, repo, branch)

    if fmt == "md":
        content = generate_markdown(mop)
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(content)
    else:
        generate_docx(mop, output)

    _log(f"MOP gerado: {output}")

    return GenerationResult(
        output_path=output,
        mop=mop,
        pending=pending,
        used_llm=used_llm,
        messages=messages,
    )
