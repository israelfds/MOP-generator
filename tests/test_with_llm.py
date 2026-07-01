"""Testes do fluxo COM LLM, com a chamada HTTP ao OpenRouter mockada.

Nenhuma requisição de rede real é feita e nenhuma API key é necessária.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

import mop_generator.llm as llm
from mop_generator.cli import cli
from mop_generator.llm import (
    LLMConfig,
    LLMError,
    apply_llm_fields,
    generate_mop_fields,
)
from mop_generator.models import GitInfo, MOP


FAKE_FIELDS = {
    "subtitle": "Novo endpoint de registro",
    "objetivo": "Permitir registro público de usuários.",
    "mudancas": [
        {"acao": "Feature", "descricao": "Adiciona /register-web", "notas": ""},
    ],
    "impacto": ["Novo endpoint público"],
    "plano_backup": "Snapshot do banco antes do deploy.",
    "validacao": "Chamar POST /register-web e validar criação.",
    "rollback": "git revert dos commits.",
    "api_changes": [
        {
            "method": "post",
            "path": "/users/register-web",
            "change_type": "Novo",
            "description": "Registro público de usuário web.",
            "request_headers": ["Content-Type: application/json"],
            "request_body": '{\n  "email": "user@x.com"\n}',
            "response_status": "201 Created",
            "response_headers": ["Content-Type: application/json"],
            "response_body": '{\n  "id": "abc"\n}',
            "notes": "",
        }
    ],
}


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _openrouter_payload(content: str):
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture
def git_info():
    return GitInfo(
        repo_url="https://dev.azure.com/Org/Proj/_git/api",
        remote_url="git@ssh.dev.azure.com:v3/Org/Proj/api",
        branch="feature/x",
        base="main",
        commits=[],
        changed_files=["a.py"],
        diff_text="diff --git a/a.py b/a.py",
    )


def test_parse_json_response_with_code_fence():
    raw = "```json\n" + json.dumps(FAKE_FIELDS) + "\n```"
    parsed = llm._parse_json_response(raw)
    assert parsed["objetivo"] == FAKE_FIELDS["objetivo"]


def test_parse_json_response_invalid_raises():
    with pytest.raises(LLMError):
        llm._parse_json_response("isto não é json")


def test_generate_mop_fields_mocked(monkeypatch, git_info):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResponse(_openrouter_payload(json_dumps_fields()))

    def json_dumps_fields():
        return json.dumps(FAKE_FIELDS)

    monkeypatch.setattr(llm.requests, "post", fake_post)

    cfg = LLMConfig(api_key="sk-test", model="deepseek/deepseek-v4-flash")
    fields = generate_mop_fields(cfg, git_info, extra_context="ctx")

    assert fields["objetivo"] == FAKE_FIELDS["objetivo"]
    # o modelo e a auth foram enviados corretamente
    assert captured["json"]["model"] == "deepseek/deepseek-v4-flash"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert "chat/completions" in captured["url"]
    # o contexto extra foi incluído no prompt
    user_msg = captured["json"]["messages"][1]["content"]
    assert "ctx" in user_msg


def test_generate_mop_fields_http_error(monkeypatch, git_info):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse({"error": "quota"}, status_code=429)

    monkeypatch.setattr(llm.requests, "post", fake_post)
    cfg = LLMConfig(api_key="sk-test")
    with pytest.raises(LLMError):
        generate_mop_fields(cfg, git_info)


def test_generate_mop_fields_requires_key(git_info):
    cfg = LLMConfig(api_key="")
    with pytest.raises(LLMError):
        generate_mop_fields(cfg, git_info)


def test_apply_llm_fields_config_precedence():
    # objetivo já veio do config; LLM não deve sobrescrever
    mop = MOP(objetivo="OBJETIVO DO CONFIG")
    apply_llm_fields(mop, FAKE_FIELDS)
    assert mop.objetivo == "OBJETIVO DO CONFIG"
    # campos vazios são preenchidos pelo LLM
    assert mop.validacao == FAKE_FIELDS["validacao"]
    assert len(mop.mudancas) == 1


def test_apply_llm_api_changes():
    mop = MOP()
    apply_llm_fields(mop, FAKE_FIELDS)
    assert len(mop.api_changes) == 1
    ep = mop.api_changes[0]
    assert ep.method == "POST"  # normalizado para maiúsculas
    assert ep.path == "/users/register-web"
    assert ep.change_type == "Novo"
    assert "email" in ep.request_body
    assert ep.response_status == "201 Created"


def test_api_section_rendered_in_markdown():
    from mop_generator.generators import generate_markdown

    mop = MOP(objetivo="obj")
    apply_llm_fields(mop, FAKE_FIELDS)
    md = generate_markdown(mop)
    assert "2. Alterações de API (Endpoints e Payloads)" in md
    assert "POST /users/register-web (Novo)" in md
    assert "Corpo da requisição (request):" in md
    assert '"email": "user@x.com"' in md


def test_api_section_rendered_in_docx(tmp_path):
    from docx import Document

    from mop_generator.generators import generate_docx

    mop = MOP(objetivo="obj")
    apply_llm_fields(mop, FAKE_FIELDS)
    out = tmp_path / "api.docx"
    generate_docx(mop, str(out))
    texts = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "2. Alterações de API (Endpoints e Payloads)" in texts
    assert "POST /users/register-web (Novo)" in texts


def test_api_section_absent_when_no_api_changes():
    from mop_generator.generators import generate_markdown

    fields = dict(FAKE_FIELDS)
    fields["api_changes"] = []
    mop = MOP(objetivo="obj")
    apply_llm_fields(mop, fields)
    md = generate_markdown(mop)
    assert "Alterações de API" not in md


def test_cli_with_llm_mocked(monkeypatch, tmp_path, git_repo):
    repo, branch, base = git_repo

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse(_openrouter_payload(json_module.dumps(FAKE_FIELDS)))

    import json as json_module

    monkeypatch.setattr(llm.requests, "post", fake_post)
    # garante que há uma "chave" para acionar o LLM
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    out = tmp_path / "mop.md"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "generate",
            "--repo",
            repo,
            "--branch",
            branch,
            "--base",
            base,
            "--format",
            "md",
            "--use-llm",
            "--model",
            "deepseek/deepseek-v4-flash",
            "--non-interactive",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    content = out.read_text(encoding="utf-8")
    assert "Permitir registro público de usuários." in content
    assert "Adiciona /register-web" in content
