"""
MEMORA Memory Manager - Command Line Entry Point

Interactive memory management CLI.
"""

import sys
import argparse
import json
from pathlib import Path

from memora.config import get_config
from memora.memory.manager import MemoryManager


def main():
    """Main entry point for memory CLI."""
    parser = argparse.ArgumentParser(
        description="MEMORA Memory Manager CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m memora.memory memorize "Content to remember" --tags python,code
  python -m memora.memory search "machine learning" --k 5
  python -m memora.memory context "project architecture"
  python -m memora.memory sources
  python -m memora.memory status
  python -m memora.memory reindex --full
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # memorize command
    mem_parser = subparsers.add_parser("memorize", help="Capture knowledge")
    mem_parser.add_argument("content", help="Content to memorize")
    mem_parser.add_argument("--tags", help="Comma-separated tags")
    mem_parser.add_argument("--source", help="Source description")

    # search command
    search_parser = subparsers.add_parser("search", help="Search memory")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--k", type=int, default=10, help="Number of results")
    search_parser.add_argument("--mode", choices=["hybrid", "keyword", "vector"], default="hybrid")
    search_parser.add_argument("--tags", help="Comma-separated tag filter")

    # context command
    ctx_parser = subparsers.add_parser("context", help="Get formatted context")
    ctx_parser.add_argument("topic", help="Topic for context")
    ctx_parser.add_argument("--k", type=int, default=5, help="Number of chunks")
    ctx_parser.add_argument("--mode", choices=["hybrid", "keyword", "vector"], default="hybrid")
    ctx_parser.add_argument("--max-chars", type=int, default=3000, help="Max context chars")

    # sources command
    subparsers.add_parser("sources", help="List indexed sources")
    subparsers.add_parser("status", help="Show index status")

    # reindex command
    reindex_parser = subparsers.add_parser("reindex", help="Re-index vault")
    reindex_parser.add_argument("--full", action="store_true", help="Full re-index")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Initialize
    config = get_config()
    config.ensure_dirs()

    if not config.validate_vault():
        print(f"ERROR: Invalid vault path: {config.vault_path}")
        sys.exit(1)

    manager = MemoryManager()

    try:
        if args.command == "memorize":
            tags = args.tags.split(",") if args.tags else None
            result = manager.memorize(args.content, tags, args.source)
            if result.success:
                print(f"✅ Memorized {result.chunk_count} chunks")
                print(f"   Chunk IDs: {', '.join(result.chunk_ids)}")
            else:
                print(f"❌ Failed: {result.message}")
                sys.exit(1)

        elif args.command == "search":
            tags = args.tags.split(",") if args.tags else None
            results = manager.search(args.query, args.k, args.mode, tags=tags)

            if not results:
                print("No results found")
                return

            print(f"Found {len(results)} results for: '{args.query}'\n")
            for i, r in enumerate(results, 1):
                source = r.file_path
                if r.heading_path:
                    source += f" > {r.heading_path}"
                print(f"{i}. [{source}] (RRF: {r.rrf_score:.3f})")
                preview = r.content[:200] + "..." if len(r.content) > 200 else r.content
                print(f"   {preview}\n")

        elif args.command == "context":
            result = manager.get_context(args.topic, args.k, args.mode, args.max_chars)

            if not result["context"]:
                print(result["message"])
                return

            print(f"Context for: '{args.topic}'")
            print(f"{result['message']}")
            print(f"Total: {result['total_chars']} chars from {result['chunk_count']} chunks\n")
            print("---")
            print(result["context"])

        elif args.command == "sources":
            sources = manager.list_sources()

            if not sources:
                print("No sources indexed")
                return

            print(f"Indexed Sources ({len(sources)}):\n")
            for s in sources:
                status_emoji = {"indexed": "✅", "modified": "⚠️", "deleted": "🗑️"}.get(s["status"], "?")
                print(f"{status_emoji} {s['path']}")
                print(f"   Status: {s['status']} | Chunks: {s['chunk_count']} | Size: {s['size']} bytes")

        elif args.command == "status":
            status = manager.status()

            print("=== MEMORA Status ===\n")
            print("Index:")
            for k, v in status["index"].items():
                print(f"  {k}: {v}")

            print("\nVector Store:")
            for k, v in status["vector_store"].items():
                print(f"  {k}: {v}")

            print("\nConfig:")
            for k, v in status["config"].items():
                print(f"  {k}: {v}")

        elif args.command == "reindex":
            print(f"Re-indexing ({'full' if args.full else 'incremental'})...")
            result = manager.reindex(full=args.full)

            print(f"\nFiles processed: {result['files_processed']}")
            print(f"Files indexed:   {result['files_indexed']}")
            print(f"Files skipped:   {result['files_skipped']}")
            print(f"Files deleted:   {result['files_deleted']}")
            print(f"Chunks created:  {result['chunks_created']}")
            print(f"Chunks deleted:  {result['chunks_deleted']}")
            print(f"Duration:        {result['duration_seconds']:.2f}s")

            if result['errors']:
                print(f"\nErrors ({len(result['errors'])}):")
                for err in result['errors'][:5]:
                    print(f"  - {err}")

    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()