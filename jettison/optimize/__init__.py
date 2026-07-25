from jettison.optimize.hooks import install_hook, is_installed, uninstall_hook
from jettison.optimize.scout import (
    add_delegation_rule,
    install_scout,
    remove_delegation_rule,
    uninstall_scout,
)

__all__ = [
    "add_delegation_rule",
    "install_hook",
    "install_scout",
    "is_installed",
    "remove_delegation_rule",
    "uninstall_hook",
    "uninstall_scout",
]
