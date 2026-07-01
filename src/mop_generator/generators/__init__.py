"""Geradores de saída do MOP (Markdown e DOCX)."""

from .markdown import generate_markdown
from .docx_gen import generate_docx

__all__ = ["generate_markdown", "generate_docx"]
