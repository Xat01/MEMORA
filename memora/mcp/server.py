"""
MEMORA MCP Server

Exposes memory capabilities via Model Context Protocol (MCP).
Tools: memorize, search_memory, get_context, list_sources, reindex
"""

import logging
from typing import Any, Dict, List, Optional

from mcp.server import MCPServer
from mcp.server.stdio import stdio_server
from mcp.types import TextContent
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from memora.memory.manager import MemoryManager
from memora.config import get_config


# Configure logging
logging.basicConfig(level=logging.INFO)
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
    limit: int = Field(default=20, description="Maximum sources to list", ge=1, le=100)


class ReindexParams(BaseModel):
    """Parameters for reindex tool."""
    full: bool = Field(default=False, description="Full re-index (ignore change detection)")


class MemoraMCPServer:
    """
    MEMORA MCP Server implementation.

    Exposes memory tools via MCP protocol.
    """

    def __init__(self, memory_manager: Optional[MemoryManager] = None):
        self.config = get_config()
        self.memory_manager = memory_manager or MemoryManager()
        self.server = MCPServer("memora")
        self._register_tools()

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
        async def list_sources(limit: int = 20) -> str:
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

    # =========================================================================
    # Health Check Endpoints
    # =========================================================================

    async def _health_live(self, request) -> JSONResponse:
        """
        GET /health/live
        Liveness probe - confirms the HTTP application is running.
        Does not perform expensive dependency checks.
        """
        return JSONResponse(
            {"status": "alive", "service": "memora"},
            status_code=200
        )

    async def _health_ready(self, request) -> JSONResponse:
        """
        GET /health/ready
        Readiness probe - determines whether MEMORA is ready to serve requests.
        Checks required storage initialization and essential application dependencies.
        """
        try:
            # Check that memory manager is initialized and storage is accessible
            status = self.memory_manager.status()
            index_stats = status.get("index", {})
            vector_info = status.get("vector_store", {})

            # Verify essential components are accessible
            checks = {
                "memory_manager": "ok",
                "sqlite": "ok" if index_stats.get("total_files", 0) >= 0 else "unavailable",
                "chromadb": "ok" if vector_info.get("count", 0) >= 0 else "unavailable",
            }

            all_ready = all(v == "ok" for v in checks.values())
            status_code = 200 if all_ready else 503

            return JSONResponse(
                {
                    "status": "ready" if all_ready else "not_ready",
                    "service": "memora",
                    "checks": checks,
                },
                status_code=status_code
            )
        except Exception as e:
            logger.error(f"Readiness check failed: {e}")
            return JSONResponse(
                {
                    "status": "not_ready",
                    "service": "memora",
                    "error": "readiness_check_failed",
                },
                status_code=503
            )

    async def _health_ollama(self, request) -> JSONResponse:
        """
        GET /health/ollama
        Reports Ollama connectivity and model availability.
        Does not expose secrets or sensitive configuration.
        """
        try:
            config = get_config()
            host = config.ollama_host
            model = config.embedding_model

            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Check Ollama connectivity
                tags_response = await client.get(f"{host}/api/tags")
                if tags_response.status_code != 200:
                    return JSONResponse(
                        {
                            "status": "unhealthy",
                            "service": "memora",
                            "component": "ollama",
                            "host": host,
                            "model": model,
                            "error": f"ollama returned {tags_response.status_code}",
                        },
                        status_code=503
                    )

                models = tags_response.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                model_available = any(model in m for m in model_names)

                return JSONResponse(
                    {
                        "status": "healthy" if model_available else "degraded",
                        "service": "memora",
                        "component": "ollama",
                        "host": host,
                        "model": model,
                        "model_available": model_available,
                        "available_models_count": len(models),
                    },
                    status_code=200 if model_available else 503
                )
        except httpx.ConnectError:
            return JSONResponse(
                {
                    "status": "unhealthy",
                    "service": "memora",
                    "component": "ollama",
                    "host": host if 'host' in locals() else config.ollama_host,
                    "error": "connection_refused",
                },
                status_code=503
            )
        except httpx.TimeoutException:
            return JSONResponse(
                {
                    "status": "unhealthy",
                    "service": "memora",
                    "component": "ollama",
                    "host": host if 'host' in locals() else config.ollama_host,
                    "error": "timeout",
                },
                status_code=503
            )
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return JSONResponse(
                {
                    "status": "unhealthy",
                    "service": "memora",
                    "component": "ollama",
                    "error": "health_check_failed",
                },
                status_code=503
            )

    async def _health_storage(self, request) -> JSONResponse:
        """
        GET /health/storage
        Checks SQLite and ChromaDB availability.
        Does not modify user data during health checks.
        """
        try:
            status = self.memory_manager.status()
            index_stats = status.get("index", {})
            vector_info = status.get("vector_store", {})

            # Check SQLite
            sqlite_ok = True
            sqlite_error = None
            try:
                from memora.storage.metadata_store import MetadataStore
                store = MetadataStore()
                stats = store.get_index_stats()
                sqlite_chunks = stats.get("total_chunks", 0)
            except Exception as e:
                sqlite_ok = False
                sqlite_error = str(e)
                sqlite_chunks = 0

            # Check ChromaDB
            chroma_ok = True
            chroma_error = None
            chroma_count = 0
            try:
                vector_count = vector_info.get("count", 0)
                chroma_count = vector_count
            except Exception as e:
                chroma_ok = False
                chroma_error = str(e)

            all_ok = sqlite_ok and chroma_ok

            return JSONResponse(
                {
                    "status": "healthy" if all_ok else "degraded",
                    "service": "memora",
                    "components": {
                        "sqlite": {
                            "status": "healthy" if sqlite_ok else "unhealthy",
                            "total_chunks": sqlite_chunks,
                            "error": sqlite_error,
                        },
                        "chromadb": {
                            "status": "healthy" if chroma_ok else "unhealthy",
                            "vector_count": chroma_count,
                            "error": chroma_error,
                        },
                    },
                },
                status_code=200 if all_ok else 503
            )
        except Exception as e:
            logger.error(f"Storage health check failed: {e}")
            return JSONResponse(
                {
                    "status": "unhealthy",
                    "service": "memora",
                    "error": "storage_check_failed",
                },
                status_code=503
            )

    async def run_http(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        """Run server with HTTP transport (streamable-http) and health endpoints."""
        import contextlib
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route

        # Create session manager for streamable-http
        session_manager = StreamableHTTPSessionManager(
            self.server._lowlevel_server,
            event_store=None,  # In-memory by default
        )

        # Lifespan manager for session manager lifecycle
        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette):
            async with session_manager.run():
                yield

        # Build routes: health endpoints + MCP transport
        # session_manager.handle_request is the ASGI callable
        routes = [
            Route("/health/live", self._health_live, methods=["GET"]),
            Route("/health/ready", self._health_ready, methods=["GET"]),
            Route("/health/ollama", self._health_ollama, methods=["GET"]),
            Route("/health/storage", self._health_storage, methods=["GET"]),
            Mount("/", app=session_manager.handle_request),
        ]

        app = Starlette(routes=routes, lifespan=lifespan)

        import uvicorn
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()


def create_server(memory_manager: Optional[MemoryManager] = None) -> MemoraMCPServer:
    """Factory function to create MEMORA MCP server."""
    return MemoraMCPServer(memory_manager)


# =========================================================================
# CLI Entry Point
# =========================================================================

async def _main_async():
    """Async main entry point for running the MCP server."""
    import sys

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


def main():
    """Synchronous entry point for console script."""
    import asyncio
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()