"""
MEMORA Command-Line Interface
"""

import sys
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from memora.config import get_config, MemoraConfig
from memora.ingestion.indexer import Indexer, create_indexer
from memora.retrieval.hybrid_search import HybridSearch
from memora.retrieval.keyword_search import KeywordSearch
from memora.retrieval.vector_search import VectorSearch
from memora.storage.metadata_store import MetadataStore
from memora.storage.vector_store import VectorStore
from memora.embeddings import create_provider
from memora.embeddings.base import EmbeddingProvider, EmbeddingResult
from memora.diagnostics import run_doctor, DoctorReport, CheckStatus

app = typer.Typer(
    name="memora",
    help="MEMORA — Local-First Personal Knowledge Infrastructure for AI",
    add_completion=False,
)
console = Console()


def _get_embedding_provider(config: MemoraConfig) -> EmbeddingProvider:
    """Create the configured embedding provider, with fallback."""
    try:
        provider = create_provider(config.embedding_provider)
        if provider.health_check():
            return provider
        raise Exception(f"{config.embedding_provider} provider not available")
    except Exception as e:
        console.print(f"[yellow]Warning: {e}[/yellow]")
        console.print("[yellow]Falling back to keyword-only search (no embeddings)[/yellow]")
        # Return a mock provider that produces zero vectors
        class MockEmbeddingProvider(EmbeddingProvider):
            @property
            def provider_name(self): return "mock"
            @property
            def model_name(self): return "mock-model"
            @property
            def dimensions(self): return config.embedding_dimensions
            def generate_embeddings(self, texts):
                return EmbeddingResult(
                    embeddings=[[0.0] * self.dimensions for _ in texts],
                    model=self.model_name,
                    dimensions=self.dimensions,
                    token_count=sum(len(t) // 4 for t in texts),
                    provider=self.provider_name,
                )
            def get_model_info(self): return {"name": self.model_name, "dimensions": self.dimensions}
            def health_check(self): return True
        return MockEmbeddingProvider()


def get_config_or_exit() -> MemoraConfig:
    """Get config, validate vault, exit on failure."""
    try:
        config = get_config()
        if not config.validate_vault():
            console.print("[red]Error:[/red] No valid Obsidian vault found.")
            if config.vault_path:
                console.print(f"  Configured path: {config.vault_path}")
            console.print("  Set VAULT_PATH in .env or as an environment variable.")
            console.print("  Run [bold]memora init[/bold] to set up configuration.")
            sys.exit(1)
        config.ensure_dirs()
        return config
    except Exception as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        sys.exit(1)


@app.command()
def init(
    vault: str = typer.Option(None, "--vault", "-v", help="Path to Obsidian vault"),
    provider: str = typer.Option("ollama", "--provider", "-p", help="Embedding provider: ollama, openai"),
):
    """Initialize MEMORA configuration (.env file)."""
    from memora.config import find_project_root, discover_obsidian_vaults

    project_root = find_project_root()
    env_path = project_root / ".env"
    example_path = project_root / ".env.example"

    # Auto-discover vault if not specified
    if not vault:
        console.print("[bold]Searching for Obsidian vaults...[/bold]")
        vaults = discover_obsidian_vaults()
        if vaults:
            console.print(f"[green]Found {len(vaults)} vault(s):[/green]")
            for i, v in enumerate(vaults):
                console.print(f"  {i+1}. {v}")
            if len(vaults) == 1:
                vault = str(vaults[0])
                console.print(f"\nUsing: {vault}")
            else:
                console.print("\nSpecify with: memora init --vault /path/to/vault")
                return
        else:
            console.print("[yellow]No Obsidian vaults found.[/yellow]")
            console.print("Specify manually: memora init --vault /path/to/vault")
            return

    # Template for fresh .env if no example exists
    default_env = f"""# =============================================================================
# MEMORA Configuration
# =============================================================================

# Obsidian Vault Path
VAULT_PATH={vault}

# Storage Paths (relative to project root)
CHROMA_PATH=./data/chromadb
SQLITE_PATH=./data/memora.db

# Embedding Provider (ollama, openai, or custom)
EMBEDDING_PROVIDER={provider}
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
OLLAMA_HOST=http://localhost:11434

# Chunking Configuration
CHUNK_SIZE=512
CHUNK_OVERLAP=50

# Search Configuration
DEFAULT_SEARCH_K=10
HYBRID_RRF_K=60

# MCP Server Configuration
MCP_TRANSPORT=stdio
MCP_HOST=127.0.0.1
MCP_PORT=8080

# Logging
LOG_LEVEL=INFO
LOG_FILE=./logs/memora.log
"""

    if not env_path.exists():
        if example_path.exists():
            content = example_path.read_text(encoding="utf-8")
            import re
            if re.search(r'^VAULT_PATH=', content, re.MULTILINE):
                content = re.sub(r'^VAULT_PATH=.*$', lambda m: f'VAULT_PATH={vault}', content, flags=re.MULTILINE)
            else:
                content += f"\nVAULT_PATH={vault}\n"
            if provider != "ollama":
                content = re.sub(r'^EMBEDDING_PROVIDER=.*$', lambda m: f'EMBEDDING_PROVIDER={provider}', content, flags=re.MULTILINE)
        else:
            content = default_env
    else:
        content = env_path.read_text(encoding="utf-8")
        console.print(f"[yellow]Updating existing .env[/yellow]")
        import re
        if re.search(r'^VAULT_PATH=', content, re.MULTILINE):
            content = re.sub(r'^VAULT_PATH=.*$', lambda m: f'VAULT_PATH={vault}', content, flags=re.MULTILINE)
        else:
            content += f"\nVAULT_PATH={vault}\n"
        if provider != "ollama":
            content = re.sub(r'^EMBEDDING_PROVIDER=.*$', lambda m: f'EMBEDDING_PROVIDER={provider}', content, flags=re.MULTILINE)

    env_path.write_text(content, encoding="utf-8")

    console.print(f"\n[green]✓[/green] Configuration saved to {env_path}")
    console.print(f"  Vault: {vault}")
    console.print(f"  Provider: {provider}")
    console.print(f"\nNext steps:")
    console.print(f"  1. Edit {env_path} to customize settings")
    console.print(f"  2. Run [bold]memora ingest[/bold] to index your vault")
    console.print(f"  3. Run [bold]memora search \"query\"[/bold] to search")


@app.command()
def status():
    """Show MEMORA index status and configuration."""
    config = get_config_or_exit()

    metadata_store = MetadataStore()
    vector_store = VectorStore()
    indexer = Indexer(metadata_store=metadata_store, vector_store=vector_store)

    stats = indexer.get_status()

    console.print(Panel.fit(
        "[bold]MEMORA Status[/bold]",
        border_style="blue"
    ))

    table = Table(show_header=False, box=None)
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Vault Path", str(config.vault_path))
    table.add_row("ChromaDB Path", str(config.chroma_path))
    table.add_row("SQLite Path", str(config.sqlite_path))
    table.add_row("Embedding Provider", config.embedding_provider)
    table.add_row("Embedding Model", config.embedding_model)
    table.add_row("Embedding Dimensions", str(config.embedding_dimensions))
    table.add_row("Chunk Size", str(config.chunk_size))
    table.add_row("Chunk Overlap", str(config.chunk_overlap))
    table.add_row("", "")
    table.add_row("Total Files Tracked", str(stats.get("total_files", 0)))
    table.add_row("Indexed Files", str(stats.get("indexed_files", 0)))
    table.add_row("Modified Files", str(stats.get("modified_files", 0)))
    table.add_row("Deleted Files", str(stats.get("deleted_files", 0)))
    table.add_row("Total Chunks", str(stats.get("total_chunks", 0)))
    table.add_row("Vector Count", str(stats.get("vector_count", 0)))
    table.add_row("Last Indexed", stats.get("last_indexed", "never"))

    console.print(table)


@app.command()
def ingest(
    full: bool = typer.Option(False, "--full", "-f", help="Full re-index (ignore change detection)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """Ingest Obsidian vault into MEMORA (incremental by default)."""
    config = get_config_or_exit()

    def progress_callback(message: str, current: int, total: int):
        if verbose or total <= 1:
            console.print(f"  [dim]{message}[/dim] ({current}/{total})")

    indexer = create_indexer(progress_callback=progress_callback)

    console.print(f"[bold]Starting ingestion[/bold] {'(full re-index)' if full else '(incremental)'}...")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Indexing...", total=None)
        stats = indexer.index(full_reindex=full)
        progress.update(task, completed=True)

    console.print("\n[bold]Ingestion Complete[/bold]")
    results_table = Table(show_header=False, box=None)
    results_table.add_column("Metric", style="cyan")
    results_table.add_column("Value", style="white")

    results_table.add_row("Files Processed", str(stats.files_processed))
    results_table.add_row("Files Indexed", str(stats.files_indexed))
    results_table.add_row("Files Skipped", str(stats.files_skipped))
    results_table.add_row("Files Deleted", str(stats.files_deleted))
    results_table.add_row("Chunks Created", str(stats.chunks_created))
    results_table.add_row("Chunks Updated", str(stats.chunks_updated))
    results_table.add_row("Chunks Deleted", str(stats.chunks_deleted))
    results_table.add_row("Embeddings Generated", str(stats.embeddings_generated))
    results_table.add_row("Duration", f"{stats.duration_seconds:.2f}s")

    if stats.errors:
        results_table.add_row("Errors", str(len(stats.errors)))
        for err in stats.errors[:5]:
            console.print(f"  [red]• {err}[/red]")
        if len(stats.errors) > 5:
            console.print(f"  [red]... and {len(stats.errors) - 5} more errors[/red]")

    console.print(results_table)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    k: int = typer.Option(10, "--k", "-k", help="Number of results"),
    mode: str = typer.Option("hybrid", "--mode", "-m", help="Search mode: hybrid, vector, keyword"),
    file: str = typer.Option(None, "--file", help="Filter by file path"),
    tag: str = typer.Option(None, "--tag", help="Filter by tag"),
    show_metadata: bool = typer.Option(False, "--meta", help="Show metadata"),
):
    """Search indexed knowledge using hybrid (keyword + vector) search."""
    config = get_config_or_exit()

    if mode not in ("hybrid", "vector", "keyword"):
        console.print(f"[red]Invalid mode:[/red] {mode}. Use: hybrid, vector, keyword")
        sys.exit(1)

    file_paths = [file] if file and not isinstance(file, typer.models.OptionInfo) else None
    tags = [tag] if tag and not isinstance(tag, typer.models.OptionInfo) else None

    # Create search components
    metadata_store = MetadataStore(db_path=config.sqlite_path)
    vector_store = VectorStore(persist_path=str(config.chroma_path))
    keyword_search = KeywordSearch(metadata_store=metadata_store)
    embedding_provider = _get_embedding_provider(config)
    vector_search = VectorSearch(vector_store=vector_store, embedding_provider=embedding_provider)
    hybrid_search = HybridSearch(keyword_search=keyword_search, vector_search=vector_search)

    console.print(f"[bold]Searching[/bold] ({mode}): [cyan]{query}[/cyan]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Searching...", total=None)
        results = hybrid_search.search(query, k=k, mode=mode, file_paths=file_paths, tags=tags)
        progress.update(task, completed=True)

    if not results:
        console.print("[yellow]No results found[/yellow]")
        return

    console.print(f"\n[bold]Found {len(results)} result(s):[/bold]\n")

    for i, result in enumerate(results, 1):
        source_color = {"hybrid": "blue", "vector": "green", "keyword": "yellow", "direct": "white"}
        color = source_color.get(result.source, "white")

        header = f"[{color}]{i}. {result.source.upper()}[/{color}]  "
        header += f"[dim]score: {result.rrf_score:.3f}[/dim]"
        if result.vector_score is not None:
            header += f"  [green]vec: {result.vector_score:.3f}[/green]"
        if result.keyword_score is not None:
            header += f"  [yellow]kw: {result.keyword_score:.3f}[/yellow]"

        console.print(header)
        console.print(f"  [cyan]{result.file_path}[/cyan]")
        if result.heading_path:
            console.print(f"  [dim]↳ {result.heading_path}[/dim]")
        if result.tags:
            console.print(f"  [dim]tags: {', '.join(result.tags)}[/dim]")

        content_preview = result.content[:500]
        if len(result.content) > 500:
            content_preview += "..."
        console.print(f"  {content_preview}")

        if show_metadata:
            console.print(f"  [dim]chunk_id: {result.chunk_id} | index: {result.chunk_index}[/dim]")

        console.print()


@app.command()
def check_provider():
    """Check embedding provider availability."""
    try:
        config = get_config()
    except Exception as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        sys.exit(1)

    console.print(f"[bold]Checking {config.embedding_provider} provider...[/bold]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Connecting...", total=None)
        try:
            provider = create_provider(config.embedding_provider)
            healthy = provider.health_check()
        except Exception as e:
            console.print(f"[red]✗ Provider error:[/red] {e}")
            sys.exit(1)
        progress.update(task, completed=True)

    if healthy:
        console.print(f"[green]✓[/green] {config.embedding_provider} provider is available")
        model_info = provider.get_model_info()
        info_table = Table(show_header=False, box=None)
        info_table.add_column("Property", style="cyan")
        info_table.add_column("Value", style="white")
        for key, value in model_info.items():
            info_table.add_row(key, str(value))
        console.print(info_table)
    else:
        console.print(f"[red]✗[/red] {config.embedding_provider} provider not available")
        if config.embedding_provider == "ollama":
            console.print(f"  Host: {config.ollama_host}")
            console.print(f"  Model: {config.embedding_model}")
            console.print("\n  Run: ollama serve")
            console.print(f"  Then: ollama pull {config.embedding_model}")
        elif config.embedding_provider == "openai":
            console.print(f"  API Base: {config.embedding_api_base}")
            console.print(f"  Model: {config.embedding_model}")
            console.print("\n  Check EMBEDDING_API_KEY and EMBEDDING_API_BASE in .env")
        sys.exit(1)


# Keep backward compatibility
@app.command(name="check-ollama", hidden=True)
def check_ollama():
    """(Deprecated: use check-provider) Check Ollama availability."""
    check_provider()


@app.command(name="pull-model")
def pull_model():
    """Pull the embedding model in Ollama."""
    try:
        config = get_config()
    except Exception as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        sys.exit(1)

    if config.embedding_provider != "ollama":
        console.print(f"[yellow]pull-model is only for Ollama. Current provider: {config.embedding_provider}[/yellow]")
        return

    from memora.embeddings.ollama_provider import OllamaProvider
    provider = OllamaProvider(host=config.ollama_host, model=config.embedding_model)

    console.print(f"[bold]Pulling model:[/bold] {config.embedding_model}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading model...", total=None)
        success = provider.pull_model()
        progress.update(task, completed=True)

    if success:
        console.print("[green]✓[/green] Model pulled successfully")
    else:
        console.print("[red]✗[/red] Failed to pull model")
        sys.exit(1)


@app.command()
def mcp():
    """Start the MCP server (stdio transport for Claude Desktop, etc.)."""
    import asyncio
    from memora.mcp.server import create_server

    try:
        config = get_config()
        config.ensure_dirs()
    except Exception as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        sys.exit(1)

    server = create_server()

    if config.mcp_transport == "http":
        console.print(f"[bold]Starting MEMORA MCP server on HTTP {config.mcp_host}:{config.mcp_port}[/bold]")
        asyncio.run(server.run_http(config.mcp_host, config.mcp_port))
    else:
        # stdio — no console output (it would corrupt the protocol)
        asyncio.run(server.run_stdio())


@app.command()
def doctor(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Run system diagnostics to verify MEMORA installation and configuration."""
    try:
        config = get_config()
    except Exception as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        config = None

    report = run_doctor(config=config, verbose=verbose, json_output=json_output)

    if not json_output:
        sys.exit(report.exit_code)


if __name__ == "__main__":
    app()
