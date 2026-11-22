"""MEMORA Lifecycle Management Module

Unified CLI for managing MEMORA deployment lifecycle.
"""

from .cli import (
    app as lifecycle_app,
    orchestrate_start,
    orchestrate_stop,
    orchestrate_restart,
    orchestrate_purge,
    get_status,
    discover_project_root,
    load_config,
)
from .dependency_manager import (
    DependencyLifecycleManager,
    StartupConfig,
    DependencyType,
    DependencyState,
    DependencyInfo,
    DockerDesktopDetector,
    OllamaDetector,
)

__all__ = [
    "lifecycle_app",
    "orchestrate_start",
    "orchestrate_stop",
    "orchestrate_restart",
    "orchestrate_purge",
    "get_status",
    "discover_project_root",
    "load_config",
    "DependencyLifecycleManager",
    "StartupConfig",
    "DependencyType",
    "DependencyState",
    "DependencyInfo",
    "DockerDesktopDetector",
    "OllamaDetector",
]