"""Interface de linha de comando do MOP Generator."""

from __future__ import annotations

import sys

import click

from . import __version__
from .core import generate_mop
from .git_utils import GitError
from .llm import LLMError


@click.group()
@click.version_option(__version__, prog_name="mop")
def cli() -> None:
    """Gera documentos MOP (Method of Procedure) a partir de um repositório Git."""


@cli.command()
@click.option(
    "--repo",
    required=True,
    help="URL SSH do repositório ou caminho local.",
)
@click.option("--branch", required=True, help="Branch a ser analisada.")
@click.option(
    "--base",
    default=None,
    help="Branch base para comparar (ex.: main). Se omitido, usa todos os commits.",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["docx", "md"]),
    default="docx",
    show_default=True,
    help="Formato de saída.",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    help="Arquivo YAML com valores padrão.",
)
@click.option(
    "--output",
    "-o",
    default=None,
    help="Caminho do arquivo de saída (padrão: gerado automaticamente).",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    default=False,
    help="Não faz perguntas; usa apenas config e dados do Git.",
)
@click.option(
    "--skip-git",
    is_flag=True,
    default=False,
    help="Não acessa o repositório Git (usa apenas config/prompts).",
)
@click.option(
    "--use-llm/--no-llm",
    "use_llm",
    default=None,
    help="Usa (ou não) o LLM via OpenRouter. Padrão: usa se OPENROUTER_API_KEY existir.",
)
@click.option(
    "--model",
    default=None,
    help="Modelo do OpenRouter (sobrescreve OPENROUTER_MODEL do .env).",
)
@click.option(
    "--llm-context",
    default="",
    help="Contexto adicional em texto passado ao LLM (ex.: motivação, requisitos).",
)
@click.option("--logo", "logo_path", default=None, help="Caminho da imagem de logo.")
@click.option(
    "--project-title", default=None, help="Título do projeto (capa/cabeçalho)."
)
@click.option(
    "--cover-title",
    default=None,
    help="Capa da modificação. Se omitido, é gerado pela LLM.",
)
@click.option("--header-text", default=None, help="Texto exibido no cabeçalho.")
def generate(
    repo: str,
    branch: str,
    base: str,
    fmt: str,
    config_path: str,
    output: str,
    non_interactive: bool,
    skip_git: bool,
    use_llm: bool,
    model: str,
    llm_context: str,
    logo_path: str,
    project_title: str,
    cover_title: str,
    header_text: str,
) -> None:
    """Gera um MOP para a BRANCH do REPO informado."""
    try:
        result = generate_mop(
            repo=repo,
            branch=branch,
            base=base,
            fmt=fmt,
            config_path=config_path,
            output=output,
            interactive=not non_interactive,
            use_llm=use_llm,
            model=model,
            llm_context=llm_context,
            skip_git=skip_git,
            logo_path=logo_path,
            project_title=project_title,
            cover_title=cover_title,
            header_text=header_text,
            log=lambda m: click.echo(m),
        )
    except (GitError, LLMError, ValueError, OSError) as exc:
        raise click.ClickException(str(exc))

    if result.pending:
        click.echo(
            "Atenção: campos pendentes (marcados como 'A preencher' no documento): "
            + ", ".join(result.pending),
            err=True,
        )


def main() -> None:
    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\nCancelado.", err=True)
        sys.exit(130)


if __name__ == "__main__":
    main()
