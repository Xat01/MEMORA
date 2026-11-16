"""
MEMORA Indexer - Command Line Entry Point

Run indexing pipeline from command line.
"""

import sys
import argparse
import asyncio
from pathlib import Path

from memora.config import get_config
from memora.ingestion.indexer import create_indexer


def progress_callback(message: str, current: int, total: int) -> None:
    """Default progress callback printing to stdout."""
    if total > 0:
        pct = (current / total) * 100
        print(f"[{current}/{total} ({pct:.1f}%)] {message}")
    else:
        print(f"[...] {message}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="MEMORA Vault Indexer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m memora.ingestion.indexer              # Incremental indexing
  python -m memora.ingestion.indexer --full       # Full re-index
  python -m memora.ingestion.indexer --watch      # Watch mode (continuous)
        """
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help="Full re-index (ignore change detection)",
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch mode for continuous indexing (not yet implemented)",
    )

    parser.add_argument(
        "--vault",
        type=str,
        help="Override vault path from config",
    )

    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress output",
    )

    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show index statistics and exit",
    )

    args = parser.parse_args()

    # Load configuration
    config = get_config()

    # Override vault path if provided
    if args.vault:
        config.vault_path = Path(args.vault)

    # Validate vault
    if not config.validate_vault():
        print(f"ERROR: Invalid vault path: {config.vault_path}")
        print("Ensure VAULT_PATH in .env points to folder containing .obsidian/")
        sys.exit(1)

    # Ensure data directories exist
    config.ensure_dirs()

    # Handle stats command
    if args.stats:
        indexer = create_indexer(progress_callback=None if args.quiet else progress_callback)
        stats = indexer.get_status()
        print("\n=== MEMORA Index Statistics ===")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        return

    # Run indexing
    print(f"MEMORA Indexer starting...")
    print(f"  Vault: {config.vault_path}")
    print(f"  Mode: {'Full re-index' if args.full else 'Incremental'}")
    print()

    progress_cb = None if args.quiet else progress_callback
    indexer = create_indexer(progress_callback=progress_cb)

    try:
        stats = indexer.index(full_reindex=args.full)

        print()
        print("=== Indexing Complete ===")
        print(f"  Files processed: {stats.files_processed}")
        print(f"  Files indexed:   {stats.files_indexed}")
        print(f"  Files skipped:   {stats.files_skipped}")
        print(f"  Files deleted:   {stats.files_deleted}")
        print(f"  Chunks created:  {stats.chunks_created}")
        print(f"  Chunks deleted:  {stats.chunks_deleted}")
        print(f"  Duration:        {stats.duration_seconds:.2f}s")

        if stats.errors:
            print(f"\n  Errors ({len(stats.errors)}):")
            for err in stats.errors[:10]:
                print(f"    - {err}")
            if len(stats.errors) > 10:
                print(f"    ... and {len(stats.errors) - 10} more")
            sys.exit(1)
        else:
            print("\n  No errors.")

    except KeyboardInterrupt:
        print("\n\nIndexing interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()