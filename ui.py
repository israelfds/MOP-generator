#!/usr/bin/env python3
"""Atalho para abrir a interface gráfica do MOP Generator.

Funciona mesmo sem `pip install`, pois adiciona a pasta `src` ao sys.path.

Uso:
    python3 ui.py
"""

import os
import sys

# Garante que o pacote em src/ seja importável sem instalação.
_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from mop_generator.ui import main  # noqa: E402

if __name__ == "__main__":
    main()
