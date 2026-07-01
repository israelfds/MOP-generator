"""Modelos de dados que representam um documento MOP."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Change:
    """Uma linha na tabela de mudanças do MOP."""

    acao: str
    descricao: str
    notas: str = ""


@dataclass
class Person:
    """Uma pessoa responsável pela execução."""

    nome: str
    email: str = ""

    def render(self) -> str:
        if self.email:
            return f"{self.nome} <{self.email}>"
        return self.nome


@dataclass
class ResponsavelTecnico:
    empresa: str = ""
    pessoas: List[Person] = field(default_factory=list)


@dataclass
class DayAfter:
    empresa: str = ""
    papel: str = ""


@dataclass
class Commit:
    """Um commit extraído da branch."""

    sha: str
    short_sha: str
    author: str
    date: str
    subject: str


@dataclass
class ProjectContext:
    """Contexto do projeto inferido do repositório (agnóstico a empresa)."""

    name: str = ""
    description: str = ""
    languages: List[str] = field(default_factory=list)
    stack: List[str] = field(default_factory=list)
    readme_excerpt: str = ""

    def has_data(self) -> bool:
        return bool(
            self.name
            or self.description
            or self.languages
            or self.stack
            or self.readme_excerpt
        )


@dataclass
class GitInfo:
    """Informações extraídas do repositório Git."""

    repo_url: str = ""
    remote_url: str = ""
    branch: str = ""
    base: str = ""
    commits: List[Commit] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)
    diff_text: str = ""
    project: Optional["ProjectContext"] = None


@dataclass
class Branding:
    """Elementos de identidade visual / padronização corporativa."""

    logo_path: str = ""       # caminho para a imagem da logo
    project_title: str = ""   # TÍTULO DO PROJETO (ex.: nome do sistema)
    cover_title: str = ""     # CAPA DA MODIFICAÇÃO (pode ser gerada pela LLM)
    header_text: str = ""     # texto exibido no cabeçalho (ex.: nome da empresa)

    def has_cover(self) -> bool:
        return bool(self.logo_path or self.project_title or self.cover_title)


@dataclass
class ApiEndpointChange:
    """Mudança em um endpoint HTTP (rota, payloads, headers)."""

    method: str = ""            # GET, POST, PUT, PATCH, DELETE
    path: str = ""              # ex.: /users/register-web
    change_type: str = ""       # Novo, Alterado, Removido
    description: str = ""
    request_headers: List[str] = field(default_factory=list)
    request_body: str = ""      # exemplo de payload (JSON/texto)
    response_status: str = ""   # ex.: 201 Created
    response_headers: List[str] = field(default_factory=list)
    response_body: str = ""     # exemplo de resposta
    notes: str = ""

    def title(self) -> str:
        base = f"{self.method} {self.path}".strip() or self.path or "Endpoint"
        if self.change_type:
            base += f" ({self.change_type})"
        return base


@dataclass
class MOP:
    """Representação completa de um documento MOP."""

    title: str = "MOP"
    subtitle: str = ""
    objetivo: str = ""
    mudancas: List[Change] = field(default_factory=list)
    upgrade_schedule: str = ""
    impacto: List[str] = field(default_factory=list)
    plano_backup: str = ""
    validacao: str = ""
    rollback: str = ""
    pull_requests: List[str] = field(default_factory=list)
    api_changes: List[ApiEndpointChange] = field(default_factory=list)
    responsavel_tecnico: ResponsavelTecnico = field(default_factory=ResponsavelTecnico)
    day_after: DayAfter = field(default_factory=DayAfter)
    acesso_devops: str = ""
    branding: Branding = field(default_factory=Branding)
    git: Optional[GitInfo] = None
