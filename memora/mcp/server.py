"""
MEMORA MCP Server

Exposes memory capabilities via Model Context Protocol (MCP).
Tools: memorize, search_memory, get_context, list_sources, reindex
"""

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from mcp.server.mcpserver import MCPServer
from mcp.server.stdio import stdio_server
from mcp.types import TextContent
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from memora.memory.manager import MemoryManager
from memora.config import get_config


import sys
# Configure logging to stderr ONLY (stdout is strictly reserved for MCP JSON-RPC protocol)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("memora.mcp")


class MemorizeParams(BaseModel):
    """Parameters for memorize tool."""
    content: str = Field(description="Text content to memorize")
    tags: Optional[List[str]] = Field(default=None, description="Optional tags")
    source: Optional[str] = Field(default=None, description="Source description")


class SearchMemoryParams(BaseModel):
    """Parameters for search_memory tool."""
    query: str = Field(description="Search query")
    k: int = Field(default=10, description="Number of results", ge=1, le=50)
    mode: str = Field(default="hybrid", description="Search mode: hybrid, keyword, or vector")
    file_paths: Optional[List[str]] = Field(default=None, description="Filter by file paths")
    tags: Optional[List[str]] = Field(default=None, description="Filter by tags")


class GetContextParams(BaseModel):
    """Parameters for get_context tool."""
    topic: str = Field(description="Topic to retrieve context for")
    k: int = Field(default=5, description="Number of chunks", ge=1, le=20)
    mode: str = Field(default="hybrid", description="Search mode")
    max_chars: int = Field(default=3000, description="Maximum context characters", ge=500, le=10000)


class ListSourcesParams(BaseModel):
    """Parameters for list_sources tool."""
    limit: Optional[int] = Field(default=None, description="Maximum sources to list (default: None for all)", ge=1)


class ReindexParams(BaseModel):
    """Parameters for reindex tool."""
    full: bool = Field(default=False, description="Full re-index (ignore change detection)")


class MemoraMCPServer:
    """
    MEMORA MCP Server implementation.

    Exposes memory tools via MCP protocol.
    """

    def __init__(self, memory_manager: Optional["MemoryManager"] = None):
        self.config = get_config()
        self._memory_manager = memory_manager
        self.server = MCPServer("memora")
        self._register_tools()

    @property
    def memory_manager(self) -> "MemoryManager":
        """Lazy-loaded MemoryManager to ensure instant MCP startup and tool listing."""
        if self._memory_manager is None:
            logger.info("Initializing MemoryManager (lazy load)...")
            from memora.memory.manager import MemoryManager
            self._memory_manager = MemoryManager()
        return self._memory_manager

    def _register_tools(self) -> None:
        """Register all MCP tools using MCP 2.3.0 API."""

        # memorize tool
        @self.server.tool()
        async def memorize(
            content: str,
            tags: Optional[List[str]] = None,
            source: Optional[str] = None,
        ) -> str:
            """Capture knowledge into memory."""
            try:
                result = self.memory_manager.memorize(
                    content=content,
                    tags=tags,
                    source=source,
                )

                if result.success:
                    return f"✅ Memorized {result.chunk_count} chunks\nChunk IDs: {', '.join(result.chunk_ids)}"
                else:
                    raise ValueError(f"Failed to memorize: {result.message}")
            except Exception as e:
                logger.error(f"Memorize error: {e}")
                raise ValueError(f"Error: {e}")

        # search_memory tool
        @self.server.tool()
        async def search_memory(
            query: str,
            k: int = 10,
            mode: str = "hybrid",
            file_paths: Optional[List[str]] = None,
            tags: Optional[List[str]] = None,
        ) -> str:
            """Search memory using hybrid search."""
            try:
                results = self.memory_manager.search(
                    query=query,
                    k=k,
                    mode=mode,
                    file_paths=file_paths,
                    tags=tags,
                )

                if not results:
                    return "No results found"

                # Format results
                lines = [f"Found {len(results)} results for: '{query}'\n"]
                for i, r in enumerate(results, 1):
                    source_info = r.file_path
                    if r.heading_path:
                        source_info += f" > {r.heading_path}"

                    score_info = f"RRF: {r.rrf_score:.3f}"
                    if r.keyword_score is not None:
                        score_info += f" | KW: {r.keyword_score:.3f}"
                    if r.vector_score is not None:
                        score_info += f" | Vec: {r.vector_score:.3f}"

                    # Truncate content for display
                    content_preview = r.content[:200] + "..." if len(r.content) > 200 else r.content

                    lines.append(f"**{i}.** [{source_info}] ({score_info})")
                    lines.append(f"    {content_preview}\n")

                return "\n".join(lines)
            except Exception as e:
                logger.error(f"Search error: {e}")
                raise ValueError(f"Error: {e}")

        # get_context tool
        @self.server.tool()
        async def get_context(
            topic: str,
            k: int = 5,
            mode: str = "hybrid",
            max_chars: int = 3000,
        ) -> str:
            """Get formatted context for a topic."""
            try:
                result = self.memory_manager.get_context(
                    topic=topic,
                    k=k,
                    mode=mode,
                    max_chars=max_chars,
                )

                if not result["context"]:
                    return result["message"]

                response = (
                    f"Context for: '{topic}'\n"
                    f"{result['message']}\n"
                    f"Total: {result['total_chars']} chars from {result['chunk_count']} chunks\n\n"
                    f"---\n\n"
                    f"{result['context']}"
                )

                return response
            except Exception as e:
                logger.error(f"Get context error: {e}")
                raise ValueError(f"Error: {e}")

        # list_sources tool
        @self.server.tool()
        async def list_sources(limit: Optional[int] = None) -> str:
            """List indexed source files."""
            try:
                sources = self.memory_manager.list_sources(limit=limit)

                if not sources:
                    return "No sources indexed"

                lines = [f"Indexed Sources ({len(sources)} shown):\n"]
                for s in sources:
                    status_emoji = "✅" if s["status"] == "indexed" else "⚠️" if s["status"] == "modified" else "🗑️"
                    lines.append(
                        f"{status_emoji} **{s['path']}**\n"
                        f"   Status: {s['status']} | Chunks: {s['chunk_count']} | "
                        f"Size: {s['size']} bytes | Indexed: {s['indexed_at']}"
                    )

                return "\n\n".join(lines)
            except Exception as e:
                logger.error(f"List sources error: {e}")
                raise ValueError(f"Error: {e}")

        # reindex tool
        @self.server.tool()
        async def reindex(full: bool = False) -> str:
            """Trigger vault re-indexing."""
            try:
                result = self.memory_manager.reindex(full=full)

                response = (
                    f"Re-indexing {'complete' if not result['errors'] else 'completed with errors'}\n\n"
                    f"Files processed: {result['files_processed']}\n"
                    f"Files indexed: {result['files_indexed']}\n"
                    f"Files skipped: {result['files_skipped']}\n"
                    f"Files deleted: {result['files_deleted']}\n"
                    f"Chunks created: {result['chunks_created']}\n"
                    f"Chunks deleted: {result['chunks_deleted']}\n"
                    f"Duration: {result['duration_seconds']:.2f}s\n"
                )

                if result['errors']:
                    response += f"\nErrors ({len(result['errors'])}):\n"
                    for err in result['errors'][:5]:
                        response += f"  - {err}\n"
                    if len(result['errors']) > 5:
                        response += f"  ... and {len(result['errors']) - 5} more\n"

                return response
            except Exception as e:
                logger.error(f"Reindex error: {e}")
                raise ValueError(f"Error: {e}")

    async def run_stdio(self) -> None:
        """Run server with stdio transport (for Claude Desktop)."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server._lowlevel_server.run(
                read_stream,
                write_stream,
                self.server._lowlevel_server.create_initialization_options(),
            )

    async def run_http(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        """Run server with HTTP transport (streamable-http)."""
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.routing import Mount

        # Create session manager for streamable-http
        session_manager = StreamableHTTPSessionManager(
            self.server._lowlevel_server,
            event_store=None,  # In-memory by default
        )

        app = Starlette(routes=[
            Mount("/", app=session_manager.streamable_http_app()),
        ])

        import uvicorn
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()


def create_server(memory_manager: Optional["MemoryManager"] = None) -> MemoraMCPServer:
    """Factory function to create MEMORA MCP server."""
    return MemoraMCPServer(memory_manager)


# =========================================================================
# CLI Entry Point
# =========================================================================

async def main():
    """Main entry point for running the MCP server."""
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(line_buffering=True)

    config = get_config()
    config.ensure_dirs()
    config.log_resolved_paths()

    server = create_server()

    if len(sys.argv) > 1 and sys.argv[1] == "http":
        host = sys.argv[2] if len(sys.argv) > 2 else config.mcp_host
        port = int(sys.argv[3]) if len(sys.argv) > 3 else config.mcp_port
        logger.info(f"Starting MEMORA MCP server on HTTP {host}:{port}")
        await server.run_http(host, port)
    else:
        logger.info("Starting MEMORA MCP server on stdio")
        await server.run_stdio()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())