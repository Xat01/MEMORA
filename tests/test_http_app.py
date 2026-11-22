"""
Tests for HTTP application initialization and StreamableHTTPSessionManager integration.
"""

import pytest
from starlette.testclient import TestClient
from memora.mcp.server import create_server


class TestHTTPAppInitialization:
    """Test HTTP application initialization and lifespan management."""

    def test_http_app_creation(self):
        """Test that the HTTP app can be created without errors."""
        server = create_server()

        # This should not raise an exception
        import asyncio
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route
        import contextlib

        session_manager = StreamableHTTPSessionManager(
            server.server._lowlevel_server,
            event_store=None,
        )

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette):
            async with session_manager.run():
                yield

        routes = [
            Route("/health/live", server._health_live, methods=["GET"]),
            Route("/health/ready", server._health_ready, methods=["GET"]),
            Route("/health/ollama", server._health_ollama, methods=["GET"]),
            Route("/health/storage", server._health_storage, methods=["GET"]),
            Mount("/", app=session_manager.handle_request),
        ]

        app = Starlette(routes=routes, lifespan=lifespan)
        assert app is not None
        assert app.router is not None

    def test_health_endpoints_exist(self):
        """Test that all health endpoints are registered."""
        server = create_server()

        import asyncio
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route
        import contextlib

        session_manager = StreamableHTTPSessionManager(
            server.server._lowlevel_server,
            event_store=None,
        )

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette):
            async with session_manager.run():
                yield

        routes = [
            Route("/health/live", server._health_live, methods=["GET"]),
            Route("/health/ready", server._health_ready, methods=["GET"]),
            Route("/health/ollama", server._health_ollama, methods=["GET"]),
            Route("/health/storage", server._health_storage, methods=["GET"]),
            Mount("/", app=session_manager.handle_request),
        ]

        app = Starlette(routes=routes, lifespan=lifespan)

        # Check that health endpoints are in the routes
        route_paths = [r.path for r in app.router.routes if hasattr(r, 'path')]
        assert "/health/live" in route_paths
        assert "/health/ready" in route_paths
        assert "/health/ollama" in route_paths
        assert "/health/storage" in route_paths

    @pytest.mark.asyncio
    async def test_health_live_endpoint(self):
        """Test that /health/live endpoint returns 200."""
        server = create_server()

        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route
        import contextlib

        session_manager = StreamableHTTPSessionManager(
            server.server._lowlevel_server,
            event_store=None,
        )

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette):
            async with session_manager.run():
                yield

        routes = [
            Route("/health/live", server._health_live, methods=["GET"]),
            Route("/health/ready", server._health_ready, methods=["GET"]),
            Route("/health/ollama", server._health_ollama, methods=["GET"]),
            Route("/health/storage", server._health_storage, methods=["GET"]),
            Mount("/", app=session_manager.handle_request),
        ]

        app = Starlette(routes=routes, lifespan=lifespan)

        with TestClient(app) as client:
            response = client.get("/health/live")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "alive"
            assert data["service"] == "memora"

    @pytest.mark.asyncio
    async def test_session_manager_lifecycle(self):
        """Test that session manager run() context manager works correctly."""
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server import MCPServer
        import contextlib
        from starlette.applications import Starlette
        from starlette.routing import Mount

        lowlevel_server = MCPServer("test")._lowlevel_server
        session_manager = StreamableHTTPSessionManager(
            lowlevel_server,
            event_store=None,
        )

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette):
            async with session_manager.run():
                yield

        app = Starlette(
            routes=[Mount("/", app=session_manager.handle_request)],
            lifespan=lifespan
        )

        # Test that the lifespan context manager can be entered and exited
        async with lifespan(app):
            pass  # Should not raise


class TestRunHTTPMethod:
    """Test the run_http method of MemoraMCPServer."""

    def test_run_http_method_exists(self):
        """Test that run_http method exists and is callable."""
        server = create_server()
        assert hasattr(server, 'run_http')
        assert callable(server.run_http)

    @pytest.mark.asyncio
    async def test_run_http_signature(self):
        """Test run_http signature has expected parameters."""
        import inspect
        server = create_server()
        sig = inspect.signature(server.run_http)
        params = list(sig.parameters.keys())
        assert 'host' in params
        assert 'port' in params
        # Check defaults
        assert sig.parameters['host'].default == "127.0.0.1"
        assert sig.parameters['port'].default == 8080