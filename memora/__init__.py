"""
MEMORA — Local-First Persistent Memory Infrastructure for AI Agents

An open-source, model-independent memory infrastructure using RAG,
Obsidian Markdown, SQLite, ChromaDB, and MCP.
"""

__version__ = "0.2.0"
__author__ = "MEMORA Contributors"
__license__ = "MIT"

from memora.config import MemoraConfig, get_config, set_config

__all__ = [
    "MemoraConfig",
    "get_config",
    "set_config",
]