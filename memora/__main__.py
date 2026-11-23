"""
MEMORA CLI Main Entrypoint.

Allows running memora directly with:
    python -m memora [command]
"""

import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        # Fast path for MCP server (Claude Desktop, etc.): bypass Typer CLI overhead
        import asyncio
        from memora.mcp.server import main
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        asyncio.run(main())
    else:
        from memora.cli import app
        app()
