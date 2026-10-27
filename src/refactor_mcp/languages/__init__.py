"""Registry of supported languages. Add a `LanguageAdapter` here to support another language."""

from __future__ import annotations

from typing import Literal

from refactor_mcp.languages.base import LanguageAdapter
from refactor_mcp.languages.python import PythonAdapter
from refactor_mcp.languages.typescript import TypeScriptAdapter

ADAPTERS: dict[str, LanguageAdapter] = {
    adapter.name: adapter for adapter in (PythonAdapter(), TypeScriptAdapter())
}

LanguageName = Literal[tuple(ADAPTERS)]
