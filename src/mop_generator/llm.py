"""Integração com LLM via OpenRouter para gerar o conteúdo do MOP.

A chave e o modelo são lidos de variáveis de ambiente (carregadas de um
arquivo `.env` quando presente):

    OPENROUTER_API_KEY   (obrigatória)
    OPENROUTER_MODEL     (opcional, padrão: openai/gpt-4o-mini)
    OPENROUTER_BASE_URL  (opcional, padrão: https://openrouter.ai/api/v1)
    OPENROUTER_APP_TITLE (opcional)
    OPENROUTER_APP_URL   (opcional)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional

import requests
from dotenv import load_dotenv

from .models import ApiEndpointChange, Change, GitInfo, MOP

DEFAULT_MODEL = "openai/gpt-4o-mini"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class LLMError(RuntimeError):
    """Erro ao chamar o LLM."""


@dataclass
class LLMConfig:
    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    app_title: str = "MOP Generator"
    app_url: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def load_llm_config(model_override: Optional[str] = None) -> LLMConfig:
    """Carrega a configuração do LLM a partir do ambiente / .env."""
    load_dotenv()  # carrega .env do diretório atual, se existir
    return LLMConfig(
        api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        model=(model_override or os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL).strip(),
        base_url=(os.getenv("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).strip(),
        app_title=os.getenv("OPENROUTER_APP_TITLE", "MOP Generator").strip(),
        app_url=os.getenv("OPENROUTER_APP_URL", "").strip(),
    )


def list_models(config: Optional[LLMConfig] = None, timeout: int = 15) -> List[str]:
    """Busca os modelos disponíveis no OpenRouter (endpoint /models).

    Retorna uma lista de IDs de modelos ordenados por nome. Se falhar (sem rede,
    sem chave, timeout), retorna uma lista com modelos populares como fallback.
    """
    fallback = [
        "deepseek/deepseek-v4-flash",
        "deepseek/deepseek-chat",
        "openai/gpt-4o-mini",
        "openai/gpt-4o",
        "anthropic/claude-sonnet-4",
        "google/gemini-2.5-flash",
    ]

    if config is None:
        config = load_llm_config()

    url = f"{config.base_url.rstrip('/')}/models"
    headers: dict = {}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return fallback
        data = resp.json()
        models = [m["id"] for m in data.get("data", []) if m.get("id")]
        return sorted(models) if models else fallback
    except Exception:
        return fallback


SYSTEM_PROMPT = (
    "Você é um engenheiro de plataforma sênior que redige documentos MOP "
    "(Method of Procedure) para deploys. A partir do contexto do projeto e das "
    "informações de uma branch Git (commits, arquivos alterados e diff), você "
    "produz o conteúdo técnico do MOP em português do Brasil, de forma objetiva, "
    "clara e profissional. Use o contexto do projeto (linguagens, stack, "
    "descrição) para tornar o objetivo, o impacto e a validação específicos e "
    "corretos. Seja agnóstico a empresa: não invente nomes de empresas, times, "
    "pessoas, datas ou links. Responda SEMPRE e SOMENTE com um objeto JSON "
    "válido, sem markdown, sem comentários e sem texto extra."
)

JSON_INSTRUCTIONS = """
Gere um JSON com exatamente as seguintes chaves:

{
  "subtitle": "resumo curto da mudança (uma linha)",
  "titulo_documento": "título formal para a capa, no formato: 'MOP para <ação> em Produção – <NOME DO PROJETO>'",
  "objetivo": "parágrafo descrevendo o objetivo do upgrade",
  "mudancas": [
    {"acao": "Melhoria|Correção|DevOps|Feature|Refatoração", "descricao": "o que muda", "notas": "observações ou vazio"}
  ],
  "impacto": ["bullet de impacto 1", "bullet de impacto 2"],
  "plano_backup": "texto do plano de backup",
  "validacao": "texto de como validar pós implementação",
  "rollback": "texto do plano de volta (rollback)",
  "api_changes": [
    {
      "method": "POST",
      "path": "/recurso/exemplo",
      "change_type": "Novo|Alterado|Removido",
      "description": "o que mudou neste endpoint",
      "request_headers": ["Content-Type: application/json", "Authorization: Bearer <token>"],
      "request_body": "{\n  \"campo\": \"valor\"\n}",
      "response_status": "201 Created",
      "response_headers": ["Content-Type: application/json"],
      "response_body": "{\n  \"id\": \"...\"\n}",
      "notes": "observações ou vazio"
    }
  ]
}

Regras:
- Baseie-se estritamente nos commits e no diff fornecidos; não invente serviços que não aparecem.
- 'mudancas' deve agrupar logicamente as alterações (não precisa ser 1 por commit).
- 'api_changes': preencha SOMENTE se o diff adicionar, alterar ou remover endpoints
  HTTP ou seus payloads/headers (rotas, controllers, views, DTOs, serializers,
  schemas OpenAPI). Caso contrário, use lista vazia []. Infira os exemplos de
  request/response a partir do código (campos de modelos/schemas), com JSON
  realista e válido. Use os headers efetivamente relevantes.
- Não inclua datas, links de PR ou nomes de responsáveis (esses são preenchidos à parte).
- Se não houver informação suficiente para um campo textual, gere uma recomendação genérica adequada a um deploy.
"""


def _build_user_prompt(git: GitInfo, extra_context: str = "") -> str:
    commits = "\n".join(
        f"- {c.short_sha} {c.subject} ({c.author})" for c in git.commits
    ) or "(nenhum commit listado)"
    files = "\n".join(f"- {f}" for f in git.changed_files) or "(nenhum arquivo)"

    parts = []

    # Contexto do projeto (agnóstico a empresa): ajuda o modelo a entender
    # o que é o projeto antes de descrever a mudança.
    proj = git.project
    if proj and proj.has_data():
        parts.append("## Contexto do projeto")
        if proj.name:
            parts.append(f"Nome: {proj.name}")
        if proj.description:
            parts.append(f"Descrição: {proj.description}")
        if proj.languages:
            parts.append(f"Linguagens: {', '.join(proj.languages)}")
        if proj.stack:
            parts.append(f"Stack/ferramentas: {', '.join(proj.stack)}")
        if proj.readme_excerpt:
            parts.append(f"Trecho do README:\n{proj.readme_excerpt}")
        parts.append("")

    parts += [
        "## Mudança na branch",
        f"Repositório: {git.repo_url}",
        f"Branch: {git.branch}",
        f"Base de comparação: {git.base or '(todos os commits)'}",
        "",
        "Commits:",
        commits,
        "",
        "Arquivos alterados:",
        files,
    ]
    if git.diff_text:
        parts += ["", "Diff (pode estar truncado):", "```diff", git.diff_text, "```"]
    if extra_context:
        parts += ["", "Contexto adicional fornecido pelo usuário:", extra_context]
    parts += ["", JSON_INSTRUCTIONS]
    return "\n".join(parts)


def _parse_json_response(content: str) -> dict:
    """Extrai o objeto JSON da resposta do modelo, tolerando cercas de código."""
    text = content.strip()
    if text.startswith("```"):
        # remove cercas ```json ... ```
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    # tenta localizar o primeiro { e o último }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Resposta do LLM não é um JSON válido: {exc}")


def generate_mop_fields(
    config: LLMConfig, git: GitInfo, extra_context: str = "", timeout: int = 120
) -> dict:
    """Chama o OpenRouter e retorna o dict com os campos do MOP gerados."""
    if not config.configured:
        raise LLMError(
            "OPENROUTER_API_KEY não configurada. Defina no .env para usar o LLM."
        )

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    if config.app_url:
        headers["HTTP-Referer"] = config.app_url
    if config.app_title:
        headers["X-Title"] = config.app_title

    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(git, extra_context)},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    url = f"{config.base_url.rstrip('/')}/chat/completions"
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise LLMError(f"Falha na requisição ao OpenRouter: {exc}") from exc

    if resp.status_code != 200:
        raise LLMError(
            f"OpenRouter retornou {resp.status_code}: {resp.text[:500]}"
        )

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError(f"Resposta inesperada do OpenRouter: {exc}") from exc

    return _parse_json_response(content)


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def apply_llm_fields(mop: MOP, fields: dict) -> MOP:
    """Aplica os campos gerados pelo LLM ao MOP, sem sobrescrever o que já existe.

    Valores vindos do config (já presentes no MOP) têm precedência sobre o LLM.
    """
    if not mop.subtitle:
        mop.subtitle = _clean(fields.get("subtitle"))
    if not mop.branding.cover_title:
        mop.branding.cover_title = _clean(fields.get("titulo_documento"))
    if not mop.objetivo:
        mop.objetivo = _clean(fields.get("objetivo"))

    if not mop.mudancas:
        mudancas: List[Change] = []
        for item in fields.get("mudancas") or []:
            if not isinstance(item, dict):
                continue
            descricao = _clean(item.get("descricao"))
            if not descricao:
                continue
            mudancas.append(
                Change(
                    acao=_clean(item.get("acao")) or "Alteração",
                    descricao=descricao,
                    notas=_clean(item.get("notas")),
                )
            )
        mop.mudancas = mudancas

    if not mop.impacto:
        mop.impacto = [_clean(i) for i in (fields.get("impacto") or []) if _clean(i)]

    if not mop.plano_backup:
        mop.plano_backup = _clean(fields.get("plano_backup"))
    if not mop.validacao:
        mop.validacao = _clean(fields.get("validacao"))
    if not mop.rollback:
        mop.rollback = _clean(fields.get("rollback"))

    if not mop.api_changes:
        api: List[ApiEndpointChange] = []
        for item in fields.get("api_changes") or []:
            if not isinstance(item, dict):
                continue
            path = _clean(item.get("path"))
            method = _clean(item.get("method"))
            if not path and not method:
                continue
            req_headers = [
                _clean(h) for h in (item.get("request_headers") or []) if _clean(h)
            ]
            resp_headers = [
                _clean(h) for h in (item.get("response_headers") or []) if _clean(h)
            ]
            api.append(
                ApiEndpointChange(
                    method=method.upper(),
                    path=path,
                    change_type=_clean(item.get("change_type")),
                    description=_clean(item.get("description")),
                    request_headers=req_headers,
                    request_body=_clean(item.get("request_body")),
                    response_status=_clean(item.get("response_status")),
                    response_headers=resp_headers,
                    response_body=_clean(item.get("response_body")),
                    notes=_clean(item.get("notes")),
                )
            )
        mop.api_changes = api

    return mop
