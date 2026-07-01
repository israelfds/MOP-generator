"""Interface gráfica (Tkinter) do MOP Generator.

Fluxo: o usuário escolhe a pasta local do repositório, seleciona a branch numa
lista, escolhe o formato e gera o MOP. A geração roda em uma thread separada
para não travar a janela.
"""

from __future__ import annotations

import os
import queue
import threading

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    _TK_IMPORT_ERROR: Exception | None = None
except Exception as _exc:  # tkinter é um pacote de sistema no Linux
    tk = None  # type: ignore
    filedialog = messagebox = ttk = None  # type: ignore
    _TK_IMPORT_ERROR = _exc

from .core import default_output, generate_mop
from .git_utils import GitError, current_branch, is_local_path, list_branches
from .llm import list_models, load_llm_config


class MopApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("MOP Generator")
        self.root.geometry("720x560")
        self._msg_queue: "queue.Queue[str]" = queue.Queue()

        self.repo_var = tk.StringVar()
        self.branch_var = tk.StringVar()
        self.base_var = tk.StringVar()
        self.format_var = tk.StringVar(value="docx")
        self.config_var = tk.StringVar()
        self.output_var = tk.StringVar()
        # Padronização / branding
        self.logo_var = tk.StringVar()
        self.project_title_var = tk.StringVar()
        self.header_text_var = tk.StringVar()
        self.cover_title_var = tk.StringVar()

        llm_cfg = load_llm_config()
        self.use_llm_var = tk.BooleanVar(value=llm_cfg.configured)
        self._llm_configured = llm_cfg.configured
        self._llm_model = llm_cfg.model
        self.model_var = tk.StringVar(value=llm_cfg.model)

        self._build_widgets()
        self._poll_queue()

    # ------------------------------------------------------------------ UI
    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        # Repositório
        ttk.Label(frm, text="Repositório (pasta local):").grid(
            row=0, column=0, sticky="w", **pad
        )
        ttk.Entry(frm, textvariable=self.repo_var).grid(
            row=0, column=1, sticky="ew", **pad
        )
        ttk.Button(frm, text="Procurar...", command=self._pick_repo).grid(
            row=0, column=2, **pad
        )

        # Branch
        ttk.Label(frm, text="Branch:").grid(row=1, column=0, sticky="w", **pad)
        self.branch_combo = ttk.Combobox(
            frm, textvariable=self.branch_var, state="readonly"
        )
        self.branch_combo.grid(row=1, column=1, columnspan=2, sticky="ew", **pad)

        # Base
        ttk.Label(frm, text="Base (opcional):").grid(row=2, column=0, sticky="w", **pad)
        self.base_combo = ttk.Combobox(
            frm, textvariable=self.base_var, state="readonly"
        )
        self.base_combo.grid(row=2, column=1, columnspan=2, sticky="ew", **pad)

        # Formato
        ttk.Label(frm, text="Formato:").grid(row=3, column=0, sticky="w", **pad)
        fmt_frame = ttk.Frame(frm)
        fmt_frame.grid(row=3, column=1, sticky="w", **pad)
        ttk.Radiobutton(
            fmt_frame, text="DOCX", value="docx", variable=self.format_var,
            command=self._update_default_output,
        ).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(
            fmt_frame, text="Markdown", value="md", variable=self.format_var,
            command=self._update_default_output,
        ).pack(side="left")

        # LLM
        llm_text = "Usar LLM (OpenRouter)"
        if not self._llm_configured:
            llm_text += " — sem OPENROUTER_API_KEY no .env"
        self.llm_check = ttk.Checkbutton(
            frm, text=llm_text, variable=self.use_llm_var
        )
        self.llm_check.grid(row=4, column=0, columnspan=2, sticky="w", **pad)
        if not self._llm_configured:
            self.llm_check.state(["disabled"])

        # Modelo LLM
        ttk.Label(frm, text="Modelo:").grid(row=5, column=0, sticky="w", **pad)
        self.model_combo = ttk.Combobox(
            frm, textvariable=self.model_var, width=40
        )
        self.model_combo.grid(row=5, column=1, columnspan=2, sticky="ew", **pad)
        # Carrega a lista de modelos em background para não travar a janela.
        self.model_combo["values"] = [self._llm_model]
        threading.Thread(target=self._load_models, daemon=True).start()

        # Config YAML
        ttk.Label(frm, text="Config YAML (opcional):").grid(
            row=6, column=0, sticky="w", **pad
        )
        ttk.Entry(frm, textvariable=self.config_var).grid(
            row=6, column=1, sticky="ew", **pad
        )
        ttk.Button(frm, text="Procurar...", command=self._pick_config).grid(
            row=6, column=2, **pad
        )

        # --- Padronização (empresa) ---
        ttk.Separator(frm, orient="horizontal").grid(
            row=7, column=0, columnspan=3, sticky="ew", pady=(10, 2)
        )
        ttk.Label(frm, text="Padronização (opcional)", font=("", 10, "bold")).grid(
            row=8, column=0, columnspan=3, sticky="w", padx=8
        )

        ttk.Label(frm, text="Logo (imagem):").grid(row=9, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.logo_var).grid(
            row=9, column=1, sticky="ew", **pad
        )
        ttk.Button(frm, text="Procurar...", command=self._pick_logo).grid(
            row=9, column=2, **pad
        )

        ttk.Label(frm, text="Título do projeto:").grid(
            row=10, column=0, sticky="w", **pad
        )
        ttk.Entry(frm, textvariable=self.project_title_var).grid(
            row=10, column=1, columnspan=2, sticky="ew", **pad
        )

        ttk.Label(frm, text="Texto do cabeçalho:").grid(
            row=11, column=0, sticky="w", **pad
        )
        ttk.Entry(frm, textvariable=self.header_text_var).grid(
            row=11, column=1, columnspan=2, sticky="ew", **pad
        )

        ttk.Label(frm, text="Capa da modificação:").grid(
            row=12, column=0, sticky="w", **pad
        )
        cover_entry = ttk.Entry(frm, textvariable=self.cover_title_var)
        cover_entry.grid(row=12, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(
            frm, text="(vazio = gerado pela LLM)", foreground="gray"
        ).grid(row=13, column=1, sticky="w", padx=8)

        # Saída
        ttk.Label(frm, text="Saída (opcional):").grid(
            row=14, column=0, sticky="w", **pad
        )
        ttk.Entry(frm, textvariable=self.output_var).grid(
            row=14, column=1, sticky="ew", **pad
        )
        ttk.Button(frm, text="Salvar como...", command=self._pick_output).grid(
            row=14, column=2, **pad
        )

        # Botão gerar
        self.generate_btn = ttk.Button(
            frm, text="Gerar MOP", command=self._on_generate
        )
        self.generate_btn.grid(row=15, column=1, sticky="e", **pad)

        # Log
        ttk.Label(frm, text="Log:").grid(row=16, column=0, sticky="nw", **pad)
        self.log_text = tk.Text(frm, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=16, column=1, columnspan=2, sticky="nsew", **pad)
        frm.rowconfigure(16, weight=1)

    # -------------------------------------------------------------- Actions
    def _load_models(self) -> None:
        """Carrega a lista de modelos do OpenRouter em background."""
        models = list_models()
        default = self._llm_model
        # Garante que o modelo default está na lista e vem primeiro.
        if default in models:
            models.remove(default)
        models.insert(0, default)

        def _update():
            self.model_combo["values"] = models

        self.root.after(0, _update)

    def _pick_repo(self) -> None:
        path = filedialog.askdirectory(title="Selecione a pasta do repositório")
        if not path:
            return
        self.repo_var.set(path)
        self._load_branches(path)
        self._update_default_output()

    def _pick_config(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecione o config.yaml",
            filetypes=[("YAML", "*.yaml *.yml"), ("Todos", "*.*")],
        )
        if path:
            self.config_var.set(path)

    def _pick_logo(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecione a logo",
            filetypes=[
                ("Imagens", "*.png *.jpg *.jpeg *.gif *.bmp"),
                ("Todos", "*.*"),
            ],
        )
        if path:
            self.logo_var.set(path)

    def _pick_output(self) -> None:
        ext = "docx" if self.format_var.get() == "docx" else "md"
        path = filedialog.asksaveasfilename(
            title="Salvar MOP como",
            defaultextension=f".{ext}",
            filetypes=[(ext.upper(), f"*.{ext}"), ("Todos", "*.*")],
        )
        if path:
            self.output_var.set(path)

    def _load_branches(self, path: str) -> None:
        if not is_local_path(os.path.join(path, ".git")) and not os.path.isdir(
            os.path.join(path, ".git")
        ):
            # ainda pode ser um repo (worktree); tentamos mesmo assim
            pass
        try:
            branches = list_branches(path)
        except GitError as exc:
            messagebox.showerror("Erro ao ler branches", str(exc))
            return
        if not branches:
            messagebox.showwarning(
                "Nenhuma branch",
                "Não foi possível listar branches. A pasta é um repositório Git?",
            )
            return

        self.branch_combo["values"] = branches
        self.base_combo["values"] = ["(todos os commits)"] + branches

        cur = current_branch(path)
        self.branch_var.set(cur if cur in branches else branches[0])
        # base padrão: main/master se existir, senão "(todos os commits)"
        for candidate in ("main", "master", "develop"):
            if candidate in branches:
                self.base_var.set(candidate)
                break
        else:
            self.base_var.set("(todos os commits)")

    def _update_default_output(self) -> None:
        repo = self.repo_var.get().strip()
        branch = self.branch_var.get().strip()
        if repo and branch:
            self.output_var.set(default_output(self.format_var.get(), repo, branch))

    def _log(self, msg: str) -> None:
        self._msg_queue.put(msg)

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _on_generate(self) -> None:
        repo = self.repo_var.get().strip()
        branch = self.branch_var.get().strip()
        if not repo:
            messagebox.showerror("Faltando", "Selecione a pasta do repositório.")
            return
        if not branch:
            messagebox.showerror("Faltando", "Selecione a branch.")
            return

        base = self.base_var.get().strip()
        if base in ("", "(todos os commits)"):
            base = None

        self.generate_btn.state(["disabled"])
        self._log("Iniciando geração...")

        args = dict(
            repo=repo,
            branch=branch,
            base=base,
            fmt=self.format_var.get(),
            config_path=self.config_var.get().strip() or None,
            output=self.output_var.get().strip() or None,
            interactive=False,  # a UI não faz prompts de terminal
            use_llm=self.use_llm_var.get(),
            model=self.model_var.get().strip() or None,
            logo_path=self.logo_var.get().strip() or None,
            project_title=self.project_title_var.get().strip() or None,
            cover_title=self.cover_title_var.get().strip() or None,
            header_text=self.header_text_var.get().strip() or None,
            log=self._log,
        )
        threading.Thread(target=self._run_generation, kwargs=args, daemon=True).start()

    def _run_generation(self, **kwargs) -> None:
        try:
            result = generate_mop(**kwargs)
        except Exception as exc:  # mostra qualquer falha na UI
            self._log(f"ERRO: {exc}")
            self.root.after(
                0, lambda: messagebox.showerror("Falha na geração", str(exc))
            )
            self.root.after(0, lambda: self.generate_btn.state(["!disabled"]))
            return

        def _done() -> None:
            self.generate_btn.state(["!disabled"])
            pend = ", ".join(result.pending) if result.pending else "nenhum"
            messagebox.showinfo(
                "MOP gerado",
                f"Documento gerado em:\n{result.output_path}\n\n"
                f"Campos pendentes (A preencher): {pend}",
            )

        self.root.after(0, _done)


def main() -> None:
    if _TK_IMPORT_ERROR is not None:
        raise SystemExit(
            "Tkinter não está disponível neste Python.\n"
            "No Debian/Ubuntu, instale o pacote de sistema:\n"
            "    sudo apt install python3-tk\n"
            "Depois rode novamente: python ui.py (ou mop-ui).\n"
            f"Detalhe: {_TK_IMPORT_ERROR}"
        )
    root = tk.Tk()
    MopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
