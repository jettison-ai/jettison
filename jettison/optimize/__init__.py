from jettison.optimize.hooks import install_hook, is_installed, uninstall_hook
from jettison.optimize.repomap import build as build_repo_map
from jettison.optimize.scout import (
    add_delegation_rule,
    add_repo_map,
    install_scout,
    remove_delegation_rule,
    remove_repo_map,
    uninstall_scout,
)

__all__ = [
    "add_delegation_rule",
    "add_repo_map",
    "build_repo_map",
    "install_hook",
    "install_scout",
    "is_installed",
    "remove_delegation_rule",
    "remove_repo_map",
    "uninstall_hook",
    "uninstall_scout",
]
