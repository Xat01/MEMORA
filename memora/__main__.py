"""
MEMORA CLI Main Entrypoint.

Allows running memora directly with:
    python -m memora [command]
"""

from memora.cli import app

if __name__ == "__main__":
    app()
