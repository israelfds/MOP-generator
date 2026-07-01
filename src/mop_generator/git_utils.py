"""Utilitários para extrair informações de um repositório Git via SSH.

Usa o binário `git` diretamente (subprocess), o que permite reutilizar a
configuração SSH já existente do usuário (chaves, ssh-agent, ~/.ssh/config).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from contextlib import contextmanager
from typing import Iterator, List, Optional, Tuple

from .models import Commit, GitInfo
from .project_context import detect_project_context


class GitError(RuntimeError):
    """Erro ao executar uma operação Git."""


def _git_env() -> dict:
    """Ambiente para os comandos git.

    Configura o SSH para não travar em modo não interativo:
    - StrictHostKeyChecking=accept-new: adiciona hosts novos automaticamente
      (evita o prompt "Are you sure you want to continue connecting"),
      mas ainda protege contra mudança de chave de um host já conhecido.
    - BatchMode=yes: nunca pede senha/passphrase interativamente; falha rápido.
    Respeita um GIT_SSH_COMMAND já definido pelo usuário.
    """
    env = os.environ.copy()
    if not env.get("GIT_SSH_COMMAND"):
        env["GIT_SSH_COMMAND"] = (
            "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
        )
    # Evita que o git abra prompts interativos de credenciais.
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


def _run_git(args: List[str], cwd: Optional[str] = None) -> str:
    """Executa um comando git e retorna a saída padrão (stripped).

    Levanta GitError com stderr em caso de falha.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            env=_git_env(),
        )
    except FileNotFoundError as exc:  # git não instalado
        raise GitError("Git não encontrado no PATH. Instale o git.") from exc
    except subprocess.CalledProcessError as exc:
        cmd = " ".join(["git", *args])
        stderr = (exc.stderr or "").strip()
        raise GitError(_friendly_git_error(cmd, stderr)) from exc
    return result.stdout.strip()


def _friendly_git_error(cmd: str, stderr: str) -> str:
    """Enriquece mensagens de erro comuns de SSH/Azure DevOps."""
    low = stderr.lower()
    if "ssh key has expired" in low or "public key authentication failed" in low:
        return (
            "Falha de autenticação SSH no Azure DevOps: sua chave pública pode "
            "ter expirado ou não estar cadastrada.\n"
            "Renove/adicione a chave em: https://aka.ms/ado-ssh-public-key-expired "
            "(User settings > SSH public keys) e teste com "
            "`ssh -T git@ssh.dev.azure.com`.\n\n"
            f"Detalhe do git:\n{stderr}"
        )
    if "permission denied (publickey)" in low:
        return (
            "Permissão negada (publickey): o SSH não conseguiu autenticar.\n"
            "Verifique se há uma chave válida no ssh-agent/~/.ssh e se ela está "
            "cadastrada no provedor.\n\n"
            f"Detalhe do git:\n{stderr}"
        )
    return f"Falha ao executar `{cmd}`:\n{stderr}"


def is_local_path(repo: str) -> bool:
    """Retorna True se `repo` aponta para um diretório local existente."""
    return os.path.isdir(os.path.expanduser(repo))


@contextmanager
def prepare_repo(repo: str, branch: str) -> Iterator[str]:
    """Garante que temos um repositório com a branch disponível.

    Se `repo` for um caminho local, usa-o diretamente. Caso contrário, faz um
    clone raso via SSH em um diretório temporário. Retorna o caminho do repo.
    """
    if is_local_path(repo):
        path = os.path.abspath(os.path.expanduser(repo))
        # Garante que a branch/refs remotas estejam atualizadas quando possível.
        try:
            _run_git(["fetch", "--all", "--prune"], cwd=path)
        except GitError:
            # Repositório local pode não ter remote; seguimos com o que existe.
            pass
        yield path
        return

    tmpdir = tempfile.mkdtemp(prefix="mop-repo-")
    try:
        # Clone completo o suficiente para comparar branches.
        _run_git(["clone", "--no-single-branch", repo, tmpdir])
        # Tenta buscar a branch alvo explicitamente (caso não venha por padrão).
        try:
            _run_git(["fetch", "origin", branch], cwd=tmpdir)
        except GitError:
            pass
        yield tmpdir
    finally:
        # Limpeza do diretório temporário.
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


def _resolve_ref(path: str, branch: str) -> str:
    """Resolve uma referência de branch (local ou remota) para uso em diff/log."""
    candidates = [branch, f"origin/{branch}"]
    for ref in candidates:
        try:
            _run_git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd=path)
            return ref
        except GitError:
            continue
    raise GitError(
        f"Branch '{branch}' não encontrada (tentado: {', '.join(candidates)})."
    )


def _merge_base(path: str, base_ref: str, branch_ref: str) -> Optional[str]:
    try:
        return _run_git(["merge-base", base_ref, branch_ref], cwd=path)
    except GitError:
        return None


def get_remote_url(path: str) -> str:
    try:
        return _run_git(["remote", "get-url", "origin"], cwd=path)
    except GitError:
        return ""


def list_branches(path: str) -> List[str]:
    """Lista as branches disponíveis (locais e remotas), sem duplicar.

    Nomes remotos são normalizados (remove o prefixo 'origin/') e HEAD é
    ignorado. Útil para popular uma lista de seleção na UI.
    """
    branches: List[str] = []
    seen = set()

    def add(name: str) -> None:
        name = name.strip()
        if name and name not in seen:
            seen.add(name)
            branches.append(name)

    # Locais
    try:
        out = _run_git(["branch", "--format=%(refname:short)"], cwd=path)
        for line in out.splitlines():
            add(line)
    except GitError:
        pass

    # Remotas (origin/*)
    try:
        out = _run_git(
            ["branch", "-r", "--format=%(refname:short)"], cwd=path
        )
        for line in out.splitlines():
            line = line.strip()
            if "->" in line or not line:
                continue  # ignora origin/HEAD -> origin/main
            if line.startswith("origin/"):
                line = line[len("origin/"):]
            add(line)
    except GitError:
        pass

    return branches


def current_branch(path: str) -> str:
    try:
        return _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    except GitError:
        return ""


def _range_expr(path: str, base: Optional[str], branch_ref: str) -> Tuple[str, str]:
    """Determina a expressão de range para log/diff.

    Retorna (range_expr, base_ref_resolvido). Se não houver base válida,
    o range cobre todos os commits alcançáveis pela branch.
    """
    if base:
        base_ref = _resolve_ref(path, base)
        mb = _merge_base(path, base_ref, branch_ref)
        if mb:
            return f"{mb}..{branch_ref}", base_ref
        return f"{base_ref}..{branch_ref}", base_ref
    return branch_ref, ""


def collect_git_info(
    path: str, repo: str, branch: str, base: Optional[str], diff_limit: int = 20000
) -> GitInfo:
    """Coleta commits, arquivos alterados, diff e remote do repositório.

    `diff_limit` limita o tamanho (em caracteres) do diff capturado para
    alimentar o LLM sem estourar o contexto. Use 0 para não capturar diff.
    """
    branch_ref = _resolve_ref(path, branch)
    range_expr, _base_ref = _range_expr(path, base, branch_ref)

    # Commits: formato sha|short|author|date|subject
    log_fmt = "%H%x1f%h%x1f%an%x1f%ad%x1f%s"
    log_out = _run_git(
        ["log", "--no-merges", f"--pretty=format:{log_fmt}", "--date=short", range_expr],
        cwd=path,
    )
    commits: List[Commit] = []
    if log_out:
        for line in log_out.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 5:
                sha, short, author, date, subject = parts
                commits.append(
                    Commit(
                        sha=sha,
                        short_sha=short,
                        author=author,
                        date=date,
                        subject=subject,
                    )
                )

    # Arquivos alterados
    diff_range = range_expr if ".." in range_expr else branch_ref
    try:
        diff_out = _run_git(["diff", "--name-only", diff_range], cwd=path)
    except GitError:
        diff_out = ""
    changed_files = [f for f in diff_out.splitlines() if f.strip()]

    # Diff textual (truncado) para contexto do LLM
    diff_text = ""
    if diff_limit and diff_limit > 0:
        try:
            diff_text = _run_git(["diff", diff_range], cwd=path)
        except GitError:
            diff_text = ""
        if len(diff_text) > diff_limit:
            diff_text = (
                diff_text[:diff_limit]
                + "\n\n[... diff truncado para caber no contexto ...]"
            )

    remote_url = get_remote_url(path)

    # Quando a entrada é um caminho local, o valor exibido como "Repositório"
    # deve ser o repositório real (URL do remote / URL web), não o path no disco.
    if is_local_path(repo):
        display_repo = ssh_to_web_url(remote_url) or remote_url or repo
    else:
        display_repo = repo

    # Contexto do projeto (linguagens, stack, nome/descrição) para o LLM.
    repo_name = (display_repo or repo).rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    project = detect_project_context(path, changed_files, repo_name)

    return GitInfo(
        repo_url=display_repo,
        remote_url=remote_url,
        branch=branch,
        base=base or "",
        commits=commits,
        changed_files=changed_files,
        diff_text=diff_text,
        project=project,
    )


def ssh_to_web_url(remote_url: str) -> str:
    """Converte uma URL SSH de remote em uma URL web navegável quando possível.

    Suporta os formatos comuns do Azure DevOps e provedores estilo GitHub.
    Retorna a própria URL se não souber converter.
    """
    if not remote_url:
        return ""

    url = remote_url.strip()

    # Azure DevOps SSH: git@ssh.dev.azure.com:v3/ORG/PROJETO/REPO
    if "ssh.dev.azure.com" in url and ":" in url:
        _, _, tail = url.partition(":")
        parts = tail.split("/")
        # espera: v3/ORG/PROJETO/REPO
        if len(parts) >= 4 and parts[0] == "v3":
            org, projeto, repo = parts[1], parts[2], parts[3]
            return (
                f"https://dev.azure.com/{org}/{projeto}/_git/{repo}"
            )

    # Formato scp genérico: git@host:owner/repo(.git)
    if url.startswith("git@") and ":" in url:
        host_part, _, path_part = url.partition(":")
        host = host_part[len("git@"):]
        path_part = path_part[:-4] if path_part.endswith(".git") else path_part
        return f"https://{host}/{path_part}"

    # ssh://git@host/owner/repo(.git)
    if url.startswith("ssh://"):
        rest = url[len("ssh://"):]
        if "@" in rest:
            rest = rest.split("@", 1)[1]
        rest = rest[:-4] if rest.endswith(".git") else rest
        # separa host do path
        if "/" in rest:
            host, _, path_part = rest.partition("/")
            return f"https://{host}/{path_part}"

    return url
