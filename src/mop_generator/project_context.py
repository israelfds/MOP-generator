"""Detecção do contexto do projeto a partir do repositório.

O objetivo é entender *o que é* o projeto e *o que mudou*, de forma
agnóstica a empresa: linguagens, stack/frameworks, nome e descrição.
Essas informações enriquecem o prompt do LLM e o documento gerado.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

from .models import ProjectContext

# Extensão -> linguagem (para inferir a partir dos arquivos).
EXT_LANG: Dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".jsx": "JavaScript (React)",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".rs": "Rust",
    ".cs": "C#",
    ".cpp": "C++",
    ".cc": "C++",
    ".c": "C",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sh": "Shell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".vue": "Vue",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
}

# Arquivo marcador -> tecnologia/ferramenta do stack.
STACK_MARKERS: Dict[str, str] = {
    "package.json": "Node.js",
    "pyproject.toml": "Python (pyproject)",
    "requirements.txt": "Python (pip)",
    "Pipfile": "Python (pipenv)",
    "poetry.lock": "Python (Poetry)",
    "go.mod": "Go modules",
    "pom.xml": "Java (Maven)",
    "build.gradle": "Gradle",
    "build.gradle.kts": "Gradle (Kotlin DSL)",
    "Cargo.toml": "Rust (Cargo)",
    "composer.json": "PHP (Composer)",
    "Gemfile": "Ruby (Bundler)",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    "docker-compose.yaml": "Docker Compose",
    "azure-pipelines.yml": "Azure Pipelines",
    "azure-pipelines.yaml": "Azure Pipelines",
    "Makefile": "Make",
    "terraform.tf": "Terraform",
    "main.tf": "Terraform",
}

# Palavras-chave de dependências -> framework (busca em manifests).
FRAMEWORK_KEYWORDS: Dict[str, str] = {
    "fastapi": "FastAPI",
    "flask": "Flask",
    "django": "Django",
    "celery": "Celery",
    "sqlalchemy": "SQLAlchemy",
    "pydantic": "Pydantic",
    "express": "Express",
    "next": "Next.js",
    "react": "React",
    "vue": "Vue",
    "angular": "Angular",
    "nestjs": "NestJS",
    "@nestjs/core": "NestJS",
    "spring-boot": "Spring Boot",
    "keycloak": "Keycloak",
    "kafka": "Kafka",
    "rabbitmq": "RabbitMQ",
    "redis": "Redis",
}

_SKIP_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    "__pycache__",
    ".idea",
    ".vscode",
    "vendor",
    "target",
}


def _read_text(path: str, limit: int = 4000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def detect_languages(path: str, changed_files: List[str], top: int = 6) -> List[str]:
    """Infere linguagens priorizando os arquivos alterados na branch.

    Combina a contagem dos arquivos modificados (foco na mudança) com uma
    varredura rasa do repositório (foco no projeto).
    """
    counts: Dict[str, int] = {}

    # Peso maior para os arquivos alterados (o foco do MOP).
    for f in changed_files:
        lang = EXT_LANG.get(os.path.splitext(f)[1].lower())
        if lang:
            counts[lang] = counts.get(lang, 0) + 3

    # Varredura rasa do repositório para entender o projeto como um todo.
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        # limita profundidade
        depth = root[len(path):].count(os.sep)
        if depth > 3:
            dirs[:] = []
            continue
        for name in files:
            lang = EXT_LANG.get(os.path.splitext(name)[1].lower())
            if lang:
                counts[lang] = counts.get(lang, 0) + 1

    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [lang for lang, _ in ranked[:top]]


def detect_stack(path: str) -> List[str]:
    """Detecta ferramentas/tecnologias por arquivos marcadores e dependências."""
    stack: List[str] = []
    seen = set()

    def add(tech: str) -> None:
        if tech and tech not in seen:
            seen.add(tech)
            stack.append(tech)

    # Marcadores em qualquer lugar (varredura rasa).
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        depth = root[len(path):].count(os.sep)
        if depth > 2:
            dirs[:] = []
            continue
        for name in files:
            if name in STACK_MARKERS:
                add(STACK_MARKERS[name])

    # Frameworks a partir de manifests conhecidos (na raiz).
    manifests = [
        "requirements.txt",
        "pyproject.toml",
        "Pipfile",
        "package.json",
        "pom.xml",
        "build.gradle",
        "composer.json",
    ]
    blob = ""
    for m in manifests:
        p = os.path.join(path, m)
        if os.path.isfile(p):
            blob += "\n" + _read_text(p).lower()
    for keyword, framework in FRAMEWORK_KEYWORDS.items():
        if keyword in blob:
            add(framework)

    return stack


def _name_desc_from_manifests(path: str) -> tuple:
    """Extrai nome/descrição de package.json ou pyproject.toml, se houver."""
    pkg = os.path.join(path, "package.json")
    if os.path.isfile(pkg):
        try:
            data = json.loads(_read_text(pkg, 8000))
            return str(data.get("name", "")), str(data.get("description", ""))
        except (ValueError, TypeError):
            pass

    pyproject = os.path.join(path, "pyproject.toml")
    if os.path.isfile(pyproject):
        text = _read_text(pyproject, 8000)
        name = _toml_value(text, "name")
        desc = _toml_value(text, "description")
        if name or desc:
            return name, desc

    return "", ""


def _toml_value(text: str, key: str) -> str:
    m = re.search(rf'^\s*{re.escape(key)}\s*=\s*"([^"]*)"', text, re.MULTILINE)
    return m.group(1) if m else ""


def _readme_excerpt(path: str, limit: int = 800) -> tuple:
    """Retorna (excerto, título, primeiro_parágrafo) do README, se existir."""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = os.path.join(path, name)
        if os.path.isfile(p):
            raw = _read_text(p, 4000)
            # remove imagens/badges markdown
            cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", raw)
            lines = [ln.rstrip() for ln in cleaned.splitlines()]

            title = ""
            for ln in lines:
                if ln.startswith("#"):
                    title = ln.lstrip("#").strip()
                    break

            # primeiro parágrafo de prosa (ignora headings, listas, código, tabelas)
            paragraph_lines: List[str] = []
            in_code = False
            for ln in lines:
                s = ln.strip()
                if s.startswith("```"):
                    in_code = not in_code
                    continue
                if in_code:
                    continue
                if not s:
                    if paragraph_lines:
                        break
                    continue
                if s[0] in "#!|>-*+" or s.startswith("["):
                    # heading, badge, tabela, citação, lista — não é prosa
                    if paragraph_lines:
                        break
                    continue
                paragraph_lines.append(s)
            paragraph = " ".join(paragraph_lines)[:limit]

            excerpt = cleaned.strip()[:limit]
            return excerpt, title, paragraph
    return "", "", ""


def detect_project_context(
    path: str, changed_files: Optional[List[str]] = None, repo_name: str = ""
) -> ProjectContext:
    """Monta o ProjectContext a partir do repositório."""
    changed_files = changed_files or []

    languages = detect_languages(path, changed_files)
    stack = detect_stack(path)

    name, description = _name_desc_from_manifests(path)
    excerpt, readme_title, readme_para = _readme_excerpt(path)

    if not name:
        name = readme_title or repo_name
    if not description:
        description = readme_para

    return ProjectContext(
        name=name.strip(),
        description=description.strip(),
        languages=languages,
        stack=stack,
        readme_excerpt=excerpt.strip(),
    )
