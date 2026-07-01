"""Carga de configuração (defaults) a partir de um arquivo YAML."""

from __future__ import annotations

from typing import Any, Dict, List

import yaml

from .models import (
    Branding,
    Change,
    DayAfter,
    MOP,
    Person,
    ResponsavelTecnico,
)


def load_config(path: str) -> Dict[str, Any]:
    """Lê um arquivo YAML e retorna um dict (vazio se o arquivo estiver vazio)."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def _clean(value: Any) -> str:
    """Normaliza texto vindo do YAML (remove espaços/quebras nas pontas)."""
    if value is None:
        return ""
    return str(value).strip()


def mop_from_config(data: Dict[str, Any]) -> MOP:
    """Constrói um MOP parcial a partir do dict de configuração."""
    mop = MOP()

    mop.title = _clean(data.get("title")) or mop.title
    mop.subtitle = _clean(data.get("subtitle"))
    mop.objetivo = _clean(data.get("objetivo"))
    mop.upgrade_schedule = _clean(data.get("upgrade_schedule"))
    mop.plano_backup = _clean(data.get("plano_backup"))
    mop.validacao = _clean(data.get("validacao"))
    mop.rollback = _clean(data.get("rollback"))
    mop.acesso_devops = _clean(data.get("acesso_devops"))

    mudancas: List[Change] = []
    for item in data.get("mudancas", []) or []:
        mudancas.append(
            Change(
                acao=_clean(item.get("acao")),
                descricao=_clean(item.get("descricao")),
                notas=_clean(item.get("notas")),
            )
        )
    mop.mudancas = mudancas

    mop.impacto = [_clean(i) for i in (data.get("impacto") or []) if _clean(i)]
    mop.pull_requests = [
        _clean(i) for i in (data.get("pull_requests") or []) if _clean(i)
    ]

    rt = data.get("responsavel_tecnico") or {}
    pessoas = [
        Person(nome=_clean(p.get("nome")), email=_clean(p.get("email")))
        for p in (rt.get("pessoas") or [])
        if _clean(p.get("nome"))
    ]
    mop.responsavel_tecnico = ResponsavelTecnico(
        empresa=_clean(rt.get("empresa")),
        pessoas=pessoas,
    )

    da = data.get("day_after") or {}
    mop.day_after = DayAfter(
        empresa=_clean(da.get("empresa")),
        papel=_clean(da.get("papel")),
    )

    branding = data.get("branding") or {}
    mop.branding = Branding(
        logo_path=_clean(branding.get("logo_path")),
        project_title=_clean(branding.get("project_title")),
        cover_title=_clean(branding.get("cover_title")),
        header_text=_clean(branding.get("header_text")),
    )

    return mop
