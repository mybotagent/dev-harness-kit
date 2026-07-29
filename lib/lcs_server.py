"""lcs_server.py — Phase 1.1 (issue #346) core URI routing + dispatcher.

Pure-function LCS server core. Reads from a :class:`ResourceRegistry`
of named handlers, returns a normalized payload shape
(``{"status": "ok|partial|error", "data": ..., ...}``), and caches
snapshots per-URI for ``ttl_seconds`` (default 5s).

Why pure functions + in-memory cache (not a real daemon):
- This is the routing + dispatcher + cache layer. The actual MCP /
  HTTP transport is a thin wrapper in a later phase.
- All handlers are pure (or close to it): they read filesystem /
  subprocess state at fetch() time. No long-lived connections.
- The cache lives across calls inside one Python process — a long-
  lived agent session is the only legitimate caller in v1.

Why the URL parser is hand-rolled (not urllib.parse):
- The ``lcs://`` scheme is internal; we don't need full RFC 3986
  compliance. The narrow surface here is: scheme prefix, slash-
  delimited segments, optional trailing slash.
- Hand-rolling keeps the read path under the 10ms p99 target.

Resource name vs path-param disambiguation:
- The parser returns all slash-delimited segments as ``path_segments``.
- The server does longest-match against the registry: ``segments[0]``,
  then ``segments[0]+"/"+segments[1]``, etc. The first registered
  match wins; the remaining segments become ``path_params``.
- This lets nested resources (``hooks/coverage``) and item-with-param
  (``interview/<session-id>``) coexist without a separate grammar.

Alias mechanism (Gap 3, issue #455):
- A handler class may declare an ``aliases`` tuple of alternate single-
  segment names. The longest-match resolver consults the alias index
  as a fallback when no primary name hits.
- Example: ``PRResource`` (name ``"pr"``) declares
  ``aliases = ("prs",)`` so ``lcs://prs`` reaches the same handler
  without registering a second resource.
- Alias clashes (alias matches another resource's name OR another
  resource's alias) raise :class:`LCSError` at registration time.
"""
from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

# ──────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────

class LCSError(Exception):
    """Raised on malformed URI / unknown resource / duplicate registration."""


class LCSPartialError(Exception):
    """Raised by a handler when fetch() can only return a partial payload.

    Carries the partial data + a list of missing-field identifiers so
    the server can convert it to a ``status=partial`` response without
    losing context about what was unavailable.
    """

    def __init__(self, data: Mapping[str, Any], missing: list[str]) -> None:
        super().__init__(f"partial: missing={missing}")
        self.data = dict(data)
        self.missing = list(missing)


# ──────────────────────────────────────────────────────────────────
# URI parsing
# ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ParsedURI:
    """Parsed form of an ``lcs://...`` URI.

    Attributes:
        path_segments: All slash-delimited segments of the URI body,
            URL-decoded. The first segment is the (top-level) resource
            name; the rest may be part of a nested resource name or
            path params, depending on what the registry exposes.
        is_collection: True iff the URI ended with ``/`` (collection
            form, e.g. ``lcs://worktrees/``).

    Note: the ``resource`` and ``path_params`` fields are NOT set by
    :func:`parse_uri` — they depend on what the registry exposes. Use
    :meth:`LCSServer.get` (which does the registry lookup) rather than
    trying to resolve the handler from the parsed URI alone.
    """

    path_segments: tuple[str, ...]
    is_collection: bool = False

    @property
    def first_segment(self) -> str:
        return self.path_segments[0] if self.path_segments else ""


def parse_uri(uri: str) -> ParsedURI:
    """Parse an ``lcs://`` URI into a :class:`ParsedURI`.

    Rules:
    - Scheme must be exactly ``lcs://`` (case-sensitive). Anything else
      raises :class:`LCSError` — silent fallback to a default would mask
      typos in hook / agent code that constructs the URI.
    - Empty URI or ``lcs://`` with no body raises.
    - The body is split on ``/``. Trailing ``/`` marks a collection.
    - ``%2F`` inside a segment is decoded as ``/`` but does NOT split
      the segment — this is what lets resources like
      ``lcs://branches/feat%2Ffoo/slot`` carry a branch name with ``/``
      intact as the first segment.
    """
    if not uri or not isinstance(uri, str):
        raise LCSError(f"URI must be a non-empty string (got {uri!r})")
    if not uri.startswith("lcs://"):
        raise LCSError(f"URI must start with 'lcs://' (got {uri!r})")
    body = uri[len("lcs://"):]
    if not body:
        raise LCSError("URI has no resource name")
    is_collection = body.endswith("/")
    if is_collection:
        body = body[:-1]
    if not body:
        raise LCSError("URI has no resource name")
    parts = body.split("/")
    path_segments = tuple(_url_unquote(p) for p in parts)
    if not path_segments or not path_segments[0]:
        raise LCSError("URI resource name is empty")
    return ParsedURI(path_segments=path_segments, is_collection=is_collection)


def _url_unquote(s: str) -> str:
    """Tiny URL unquote — only handles ``%XX`` escapes. Path segments
    are kept verbatim otherwise (no '+' → space conversion; LCS URIs
    don't carry query strings)."""
    if "%" not in s:
        return s
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "%" and i + 2 < len(s):
            try:
                out.append(bytes([int(s[i + 1:i + 3], 16)]).decode("ascii"))
                i += 3
                continue
            except (ValueError, UnicodeDecodeError):
                pass
        out.append(ch)
        i += 1
    return "".join(out)


def _resolve_resource(
    parsed: ParsedURI, registry: "ResourceRegistry",
) -> tuple["Resource", tuple[str, ...]]:
    """Longest-match a :class:`ParsedURI` against the registry.

    Returns ``(handler, path_params)`` where ``path_params`` is the
    tuple of segments after the matched resource name. If no match,
    raises :class:`LCSError`.

    Lookup order:
    1. Longest-match against the primary-name index — every prefix
       length from longest to shortest. The first registered name wins.
    2. If no primary match, fall back to a single-segment alias match
       on ``segments[0]``. Aliases are always single-segment (no
       nesting); the remaining segments become ``path_params``.

    The alias fallback exists so a resource can be reached under
    multiple URI spellings (e.g. ``PRResource`` under both
    ``lcs://pr/<n>`` and ``lcs://prs``) without registering a second
    handler.
    """
    segments = parsed.path_segments
    # Primary lookup: every prefix length, longest first.
    for n in range(len(segments), 0, -1):
        candidate = "/".join(segments[:n])
        if candidate in registry._by_name:  # noqa: SLF001 — internal index
            return registry._by_name[candidate], segments[n:]  # noqa: SLF001
    # Alias fallback: single-segment match on segments[0].
    first = segments[0]
    if first in registry._aliases:  # noqa: SLF001
        return registry._aliases[first], segments[1:]  # noqa: SLF001
    raise LCSError(
        f"no registered resource matches URI segments {segments!r} "
        f"(tried {len(segments)} prefix lengths + alias fallback)"
    )


# ──────────────────────────────────────────────────────────────────
# Resource protocol + registry
# ──────────────────────────────────────────────────────────────────

class Resource(Protocol):
    """Interface implemented by every LCS resource handler.

    Handlers receive a :class:`ParsedURI` and return a dict with at
    minimum a ``status`` key (``"ok"`` / ``"partial"``). The server
    wraps raw handler exceptions into ``status="error"`` payloads so
    the read path never raises. Handlers that want a partial status
    should return the dict directly OR raise :class:`LCSPartialError`.

    Handlers MAY declare ``aliases`` (tuple of strings) as a class
    attribute. Each alias is an alternate single-segment name under
    which the same handler can be reached. Aliases are only consulted
    when no primary longest-match hit; they never shadow a primary
    name. Clashes at registration time raise :class:`LCSError`.
    """

    name: str
    aliases: tuple[str, ...]

    def fetch(self, parsed: ParsedURI) -> dict: ...


class ResourceRegistry:
    """Map of resource name → handler instance + alias → handler.

    Registration order is preserved for diagnostic listings, but lookup
    is by name only. Duplicate primary registration raises
    :class:`LCSError` so a typo in the handler's ``name`` attribute
    can't silently shadow an existing handler. Aliases are validated
    against both the primary index and the alias index; either kind
    of clash raises :class:`LCSError`.
    """

    def __init__(self) -> None:
        # _by_name: primary name -> handler (longest-match lookup).
        self._by_name: dict[str, Resource] = {}
        # _aliases: alias -> handler (single-segment fallback).
        self._aliases: dict[str, Resource] = {}

    def register(self, resource: Resource) -> None:
        name = getattr(resource, "name", None)
        if not name:
            raise LCSError(f"resource {resource!r} has no 'name' attribute")
        if name in self._by_name:
            raise LCSError(
                f"resource {name!r} already registered "
                f"(existing={self._by_name[name]!r}, new={resource!r})"
            )
        # The new primary name must not shadow an already-registered
        # alias of a different resource. (Aliases of the SAME resource
        # are allowed and meaningful only when the alias differs from
        # the primary; identical alias == name is treated as redundant
        # below.)
        if name in self._aliases:
            raise LCSError(
                f"resource {name!r} clashes with an already-registered "
                f"alias (owner={self._aliases[name]!r})"
            )
        # Validate aliases (defaults to empty tuple when unset).
        aliases = tuple(getattr(resource, "aliases", ()) or ())
        for alias in aliases:
            if not isinstance(alias, str) or not alias:
                raise LCSError(
                    f"resource {name!r} has invalid alias {alias!r} "
                    f"(must be non-empty string)"
                )
            if "/" in alias:
                raise LCSError(
                    f"resource {name!r} alias {alias!r} contains '/' "
                    f"(aliases are single-segment only)"
                )
            if alias == name:
                # Redundant: same string as the primary name. Silently
                # skip rather than raise — the dispatcher already routes
                # the primary name correctly, and a self-alias only
                # risks double-indexing noise.
                continue
            if alias in self._by_name:
                raise LCSError(
                    f"resource {name!r} alias {alias!r} clashes with "
                    f"an already-registered primary name "
                    f"(owner={self._by_name[alias]!r})"
                )
            if alias in self._aliases:
                raise LCSError(
                    f"resource {name!r} alias {alias!r} clashes with "
                    f"an already-registered alias "
                    f"(owner={self._aliases[alias]!r})"
                )
        # Commit: primary first, then aliases (skipping self-aliases).
        self._by_name[name] = resource
        for alias in aliases:
            if alias == name:
                continue
            self._aliases[alias] = resource

    def get(self, name: str) -> Resource:
        # Primary lookup first; alias fallback only if not found.
        if name in self._by_name:
            return self._by_name[name]
        if name in self._aliases:
            return self._aliases[name]
        raise LCSError(f"unknown resource {name!r}")

    def __contains__(self, name: str) -> bool:
        return name in self._by_name or name in self._aliases

    def __len__(self) -> int:
        # Length counts primary registrations only; aliases are an
        # alternate route to the same handler instance.
        return len(self._by_name)


# ──────────────────────────────────────────────────────────────────
# Server
# ──────────────────────────────────────────────────────────────────

@dataclass
class _CacheEntry:
    payload: dict
    expires_at: float


class LCSServer:
    """URI router + dispatcher + snapshot cache.

    Stateless beyond the in-memory cache. A new server instance per
    process is the expected pattern (each consumer owns one). The
    cache is per-instance, so two servers see independent TTLs.

    Thread-safety: NOT thread-safe in v1. The agent runtime is
    single-threaded per session. If that assumption changes, the
    cache mutations need a lock.
    """

    def __init__(
        self,
        registry: ResourceRegistry,
        *,
        ttl_seconds: float = 5.0,
        clock: "callable[[], float]" = time.monotonic,
    ) -> None:
        self._registry = registry
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[str, _CacheEntry] = {}

    def get(self, uri: str) -> dict:
        """Fetch the resource at ``uri``.

        Cached snapshot returned if one exists within the TTL window.
        Otherwise: parse URI, longest-match against the registry,
        dispatch to the matching handler, wrap the result in the
        standard response shape, and cache.

        Status of returned dict:
        - ``"ok"``      — handler returned a complete payload.
        - ``"partial"`` — handler returned partial payload (either via
          ``status="partial"`` dict, or by raising ``LCSPartialError``).
        - ``"error"``   — handler raised an unexpected exception. The
          ``"error"`` key carries a stringified form.
        """
        now = self._clock()
        cached = self._cache.get(uri)
        if cached is not None and cached.expires_at > now and self._ttl > 0:
            return cached.payload

        parsed = parse_uri(uri)
        handler, _path_params = _resolve_resource(parsed, self._registry)
        try:
            payload = handler.fetch(parsed)
        except LCSPartialError as exc:
            payload = {
                "status": "partial",
                "data": exc.data,
                "missing": exc.missing,
            }
        except Exception as exc:  # noqa: BLE001 — handler failure is a payload, not a crash
            payload = {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }

        # Normalize: every payload MUST have a status key. Handlers may
        # omit it by mistake; default to "ok" since the call returned.
        if "status" not in payload:
            payload = {"status": "ok", **payload}

        if self._ttl > 0:
            self._cache[uri] = _CacheEntry(
                payload=payload,
                expires_at=now + self._ttl,
            )
        return payload

    def invalidate(self, uri: str | None = None) -> None:
        """Drop cached snapshot(s). Pass ``None`` to clear the whole cache."""
        if uri is None:
            self._cache.clear()
        else:
            self._cache.pop(uri, None)
