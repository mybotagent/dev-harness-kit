"""lcs_resources — Live Context Server resource handlers (Phase 1.3+).

Each module in this package implements one ``lcs://`` resource.
Importing a module registers the resource with the LCS server's
default registry, so a one-line ``import lcs_resources.worktrees`` is
all a consumer needs to expose ``lcs://worktrees`` to its agent.
"""
