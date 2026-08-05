"""session_monitor_picker.py -- inline arrow-key picker (termios + ANSI).

Splits the interactive picker out of ``tools/session_monitor.py``. The
picker is a single-pane inline UI built directly on ``termios`` and
ANSI escapes -- no ``curses``, no third-party deps. The intent mirrors
Claude Code's ``AskUserQuestion``: arrow keys to move, Enter to
resume, ``q`` / ``Esc`` / ``Ctrl-C`` to cancel. Rendering stays inside
the terminal's normal scrollback so the user never loses their last
command's output.

Live search: inside the picker, ``/`` enters edit mode where the
buffer is a substring pattern applied on top of any ``--filter``
narrowing the CLI may have already done. ``/edit`` / ``Backspace`` /
``Esc`` (two-phase) / ``Enter`` (select) / ``q`` (quit) / ``j``/``k``/
arrows (move) are the keys; Ctrl-C still raises KeyboardInterrupt so
the outer try/except can return ``None`` cleanly.

Public surface (re-exported by ``tools/session_monitor.py`` so callers
keep using ``sm.pick_session``, ``sm.build_rows``, etc.):
- ``_ANSI``, ``_STATUS_COLOR``
- ``build_rows``, ``_selectable_indices``, ``_move_selectable``,
  ``_clamp_cursor``, ``_rebuild_rows_with_query``
- ``_step_normal``, ``_step_editing``
- ``_terminal_size``, ``_render_picker``, ``_read_key``
- ``pick_session``
"""
from __future__ import annotations

import os
import select
import sys
import termios
from datetime import datetime, timezone

# When imported as ``session_monitor.picker`` from the parent module,
# the parent has already inserted ``tools/`` on sys.path; when run
# standalone for tests, this is a no-op since the import is by name only.
# Dataclasses come from session_monitor_types to keep the load order safe
# under `python3 tools/session_monitor.py --help` (no top-level
# session_monitor module yet under the __main__ entrypoint).
from session_monitor_filter import filter_model  # noqa: E402
from session_monitor_format import (  # noqa: E402
    _GLYPH,
    _column_header,
    _commit_cell,
    _rel_time,
    _src_tag,
    group_by_state,
)
from session_monitor_types import Session, Status, WorktreeInfo  # noqa: E402

_ANSI = {
    "reset":      "\x1b[0m",
    "bold":       "\x1b[1m",
    "dim":        "\x1b[2m",
    "reverse":    "\x1b[7m",
    "hide_cur":   "\x1b[?25l",
    "show_cur":   "\x1b[?25h",
    "home":       "\x1b[H",
    "clear_eol":  "\x1b[K",
    "green":      "\x1b[32m",
    "yellow":     "\x1b[33m",
    "red":        "\x1b[31m",
    "cyan":       "\x1b[36m",
}

_STATUS_COLOR = {
    Status.LIVE: "green",
    Status.IDLE: "yellow",
    Status.STALE: "red",
}

# Sentinel returned by the step helpers when the underlying OS signal
# (Ctrl-C) needs to be re-raised; using a module-private object instead
# of a magic string keeps the call site type-checkable and immune to
# typos in the literal.
_RAISE = object()


def build_rows(model: list[WorktreeInfo], *,
               now: datetime | None = None) -> list[dict]:
    """Flatten a worktree model into header + session rows for the picker.

    Pure function -- testable without a TTY. Emits three row kinds:

    - ``"section"`` — top-level bucket label ("LIVE", "MERGED", ...) with
      no ``session`` key; not selectable.
    - ``"header"``  — per-worktree title with state + commit subject; not
      selectable.
    - ``"columns"`` — column-label row beneath each header; not selectable.
    - ``"session"`` — selectable row carrying a ``Session`` payload.

    The picker only lands its cursor on session rows (see
    ``_move_selectable``).
    """
    now = now or datetime.now(timezone.utc)
    rows: list[dict] = []
    sections = group_by_state(model)
    for label, wts in sections:
        section_total = sum(len(w.sessions) for w in wts)
        rows.append({
            "kind": "section",
            "text": (f"── {label.upper()}  ({len(wts)} worktrees, "
                     f"{section_total} sessions) " + "─" * 30),
        })
        for w in wts:
            tag = f"  last: \"{w.last_commit_subject}\"" if w.last_commit_subject else ""
            rows.append({
                "kind": "header",
                "text": (f"  ▸ {w.dirname}  [{w.state}]  "
                         f"({len(w.sessions)} sessions){tag}"),
            })
            rows.append({"kind": "columns", "text": _column_header("  ")})
            for s in w.sessions:
                sub = f" +{s.subagent_count}agt" if s.subagent_count else ""
                rows.append({
                    "kind": "session",
                    "text": (f"  {_GLYPH[s.status]} {s.status.value:5} "
                             f"{_src_tag(s.source):<3} "
                             f"{s.session_id[:8]} {s.model[:14]:14} "
                             f"{s.branch[:22]:22} "
                             f"{_rel_time(s.last_ts, now):>9}  "
                             f"{_commit_cell(w.last_commit_subject)}{sub}"),
                    "session": s,
                })
    return rows


def _selectable_indices(rows: list[dict]) -> list[int]:
    return [i for i, r in enumerate(rows) if r["kind"] == "session"]


def _move_selectable(rows: list[dict], cursor: int, delta: int) -> int:
    """Move the cursor by ``delta`` session rows, never landing on a header."""
    sel = _selectable_indices(rows)
    if not sel:
        return cursor
    if cursor in sel:
        pos = sel.index(cursor)
    else:
        # cursor was on a header; land on the nearest selectable row
        pos = len(sel)
        for j, idx in enumerate(sel):
            if idx >= cursor:
                pos = j
                break
    target = max(0, min(pos + delta, len(sel) - 1))
    return sel[target]


def _move(rows: list[dict], cursor: int, delta: int, mode: str
          ) -> tuple[list[dict], int, str]:
    """Shared move-with-key helper for both picker modes.

    Returns ``(rows, cursor, mode)`` so the caller can rebind without
    re-inspecting the key. ``mode`` is threaded through unchanged --
    the only thing the helper decides is the new cursor position.
    """
    return rows, _move_selectable(rows, cursor, delta), mode


def _clamp_cursor(rows: list[dict], cursor: int) -> int:
    """Re-snap the cursor onto a selectable row after a row-list rebuild.

    Preserves the cursor when it still lands on a session row; otherwise
    snaps forward to the next selectable row, and returns the last
    selectable row when ``cursor`` is past the end. Returns 0 when the
    row set has no selectable rows at all (caller can then exit cleanly).
    """
    sel = _selectable_indices(rows)
    if not sel:
        return 0
    if cursor in sel:
        return cursor
    for i in sel:
        if i >= cursor:
            return i
    return sel[-1]


def _rebuild_rows_with_query(
    model: list[WorktreeInfo],
    buffer: str,
    prev_session: Session | None,
) -> tuple[list[dict], int]:
    """Build rows from ``filter_model(model, buffer)`` and place the cursor.

    ``prev_session`` is the session that the cursor was on before the
    rebuild, or ``None`` when there was nothing to preserve. The function
    returns the cursor pointing at the row whose payload session has the
    same ``session_id`` as ``prev_session`` when one survives the filter --
    so a narrowing buffer does not silently jump to a *different* session.
    Falls back to ``_clamp_cursor(rows, 0)`` (first selectable row) when
    the previous session was filtered out or no previous session existed.
    """
    filtered = filter_model(model, buffer)
    rows = build_rows(filtered)
    if prev_session is not None:
        prev_id = prev_session.session_id
        for i, r in enumerate(rows):
            if (r["kind"] == "session"
                    and r["session"].session_id == prev_id):
                return rows, i
    return rows, _clamp_cursor(rows, 0)


def _terminal_size(fallback: tuple[int, int] = (80, 24)) -> tuple[int, int]:
    try:
        return os.get_terminal_size(0)
    except OSError:
        return fallback


def _render_picker(out, rows: list[dict], cursor: int, scroll: int,
                   max_x: int, max_y: int, query: str = "",
                   total_sessions: int | None = None) -> None:
    """Write the picker frame to ``out`` (one full redraw per call).

    Layout: 1 header line + body + 1 footer line. ``max_x`` and ``max_y``
    are the caller's terminal size in columns / rows; this function does
    not query the terminal itself so the same call can be unit-tested.

    With ``query=""`` the output is byte-identical to the legacy
    layout (legacy ``N sessions / M worktrees`` header + NORMAL-mode
    key-hint footer). With ``query!=""`` the header switches to
    ``/<query>  N / M matches`` (post-filter / pre-filter totals) and
    the footer switches to the edit-mode key hints; a zero-match
    buffer additionally appends ``  0 matches  `` so the user can read
    why the body is empty without scrolling.
    """
    body_h = max(1, max_y - 2)
    sess_total = sum(1 for r in rows if r["kind"] == "session")
    wt_total = sum(1 for r in rows if r["kind"] == "header")
    if query:
        n_post = sess_total
        m_pre = total_sessions if total_sessions is not None else sess_total
        head = f" session-monitor  /{query}  {n_post} / {m_pre} matches "
    else:
        head = (f" session-monitor  {sess_total} sessions "
                f"/ {wt_total} worktrees ")

    out.write(_ANSI["home"] + _ANSI["hide_cur"])
    out.write(_ANSI["bold"] + _ANSI["cyan"] + head.ljust(max_x) + _ANSI["reset"] + "\n")

    visible_end = min(scroll + body_h, len(rows))
    for i in range(scroll, visible_end):
        r = rows[i]
        text = r["text"][: max_x - 1]
        if r["kind"] in ("section", "header", "columns"):
            out.write(_ANSI["dim"] + text.ljust(max_x) + _ANSI["reset"] + "\n")
            continue
        color = _STATUS_COLOR.get(r["session"].status)
        prefix = _ANSI[color] if color else ""
        if i == cursor:
            out.write(_ANSI["reverse"] + prefix + text.ljust(max_x)
                      + _ANSI["reset"] + "\n")
        else:
            out.write(prefix + text.ljust(max_x) + _ANSI["reset"] + "\n")

    for _ in range(body_h - (visible_end - scroll)):
        out.write(_ANSI["clear_eol"] + "\n")

    if query:
        footer = " /edit   Backspace del   Esc clear/quit-search   Enter select   q quit "
        if sess_total == 0:
            footer = footer + "  0 matches  "
    else:
        footer = " ↑↓ / j k move   Enter resume   q / Esc / Ctrl-C quit "
    out.write(_ANSI["reverse"] + footer.ljust(max_x) + _ANSI["reset"])
    out.flush()


def _read_key(timeout: float = 0.5) -> bytes:
    """Read one logical keypress from stdin, with timeout.

    Resolves ``ESC [ A/B`` into single bytes ``b"\\x1b[A"`` /
    ``b"\\x1b[B"`` so the caller can match arrow keys directly. A lone
    ``ESC`` (no follow-up byte within 50 ms) is returned as-is.
    """
    rlist, _, _ = select.select([0], [], [], timeout)
    if not rlist:
        return b""
    b = os.read(0, 1)
    if b != b"\x1b":
        return b
    rlist, _, _ = select.select([0], [], [], 0.05)
    if not rlist:
        return b"\x1b"  # lone ESC
    nxt = os.read(0, 1)
    if nxt != b"[":
        return b"\x1b" + nxt
    rlist, _, _ = select.select([0], [], [], 0.05)
    if not rlist:
        return b"\x1b["
    return b"\x1b[" + os.read(0, 1)


def _session_at_cursor(rows: list[dict], cursor: int) -> Session | None:
    """Return the Session the cursor is on, or None when on a non-session row."""
    if not rows:
        return None
    if cursor < 0 or cursor >= len(rows):
        return None
    r = rows[cursor]
    if r.get("kind") != "session":
        return None
    return r.get("session")


def _step_normal(
    key: bytes,
    rows: list[dict],
    cursor: int,
    buffer: str,
    original_model: list[WorktreeInfo],
) -> tuple[list[dict], int, str, str, Session | None, bool]:
    """Pure handler for a NORMAL-mode keypress.

    Returns ``(rows, cursor, buffer, mode, returned_session, should_exit)``.

    Quits: ``\\x1b``, ``b"q"``, ``b"Q"`` → ``should_exit=True`` with
    ``returned_session=None``.
    Selection: ``b"\\r"`` / ``b"\\n"`` → ``should_exit=True`` with
    ``returned_session`` set to the row under the cursor when there is
    a selectable match (Enter is otherwise a no-op).
    State changes: arrows / j/k move the cursor; ``b"/"`` switches to
    EDITING; any other printable char seeds the EDITING buffer with
    that character and rebuilds the rows.

    The 6th tuple slot (``should_exit``) cleanly distinguishes "quit"
    from "no-op" so ``pick_session`` does not have to re-inspect ``key``
    after every call.
    """
    # Enter: select the row at the cursor, or no-op when no rows.
    if key in (b"\r", b"\n"):
        sel = _selectable_indices(rows)
        if not sel:
            return rows, cursor, buffer, "NORMAL", None, False
        return rows, cursor, buffer, "NORMAL", rows[cursor]["session"], True

    # Esc / q / Q: quit.
    if key == b"\x1b" or key in (b"q", b"Q"):
        return rows, cursor, buffer, "NORMAL", None, True

    # Move up.
    if key == b"\x1b[A" or key in (b"k", b"K"):
        return _move(rows, cursor, -1, "NORMAL") + (buffer, "NORMAL", None, False)

    # Move down.
    if key == b"\x1b[B" or key in (b"j", b"J"):
        return _move(rows, cursor, +1, "NORMAL") + (buffer, "NORMAL", None, False)

    # Enter edit mode (slash with no characters yet).
    if key == b"/":
        return rows, cursor, buffer, "EDITING", None, False

    # Printable: seed the edit buffer with this character and rebuild.
    if len(key) == 1 and 32 <= key[0] < 127:
        ch = key.decode("utf-8", errors="replace")
        prev = _session_at_cursor(rows, cursor)
        new_rows, new_cursor = _rebuild_rows_with_query(original_model, ch, prev)
        return new_rows, new_cursor, ch, "EDITING", None, False

    # Unknown key: no-op.
    return rows, cursor, buffer, "NORMAL", None, False


def _step_editing(
    key: bytes,
    rows: list[dict],
    cursor: int,
    buffer: str,
    original_model: list[WorktreeInfo],
) -> tuple[list[dict], int, str, str, Session | None, bool]:
    """Pure handler for an EDITING-mode keypress.

    Returns ``(rows, cursor, buffer, mode, returned_session, should_exit)``.

    Selection: ``b"\\r"`` / ``b"\\n"`` → ``should_exit=True`` with the
    row at the cursor when at least one match survives (otherwise
    drops the picker back to NORMAL mode but keeps the buffer so
    the user can refine instead of retype).
    Esc: two-phase clear. With a non-empty buffer, clears the buffer
    and stays in EDITING (rebuilding from the original unfiltered
    model). With an empty buffer, returns to NORMAL.
    ``\\b`` / ``\\x7f``: drop the last buffer char (no-op on empty),
    then rebuild so the row set narrows immediately.
    Arrows / j/k: move the cursor without touching the buffer.
    Printables: append to the buffer (q, Q, slash are literal here
    so the user can search for them), then rebuild.
    Ctrl-C (``b"\\x03"``): re-raised so the outer ``try/except`` in
    ``pick_session`` converts it to a clean ``None`` return.
    """
    # Enter: select the row at the cursor, or drop to NORMAL when
    # the filter has dropped every match (the buffer is kept so the
    # user can refine without retyping).
    if key in (b"\r", b"\n"):
        sel = _selectable_indices(rows)
        if not sel:
            return rows, cursor, buffer, "NORMAL", None, False
        return rows, cursor, buffer, "EDITING", rows[cursor]["session"], True

    # Ctrl-C: keep ISIG on so the OS raises KeyboardInterrupt, which
    # the outer except turns into a clean None return. We re-raise
    # explicitly so the helper remains pure for its structured state
    # transitions and the kernel-level signal still works on a real
    # TTY.
    if key == b"\x03":
        return rows, cursor, buffer, "EDITING", _RAISE, True

    # Two-phase Esc: first press clears the buffer (stays in
    # EDITING); an empty buffer exits EDITING to NORMAL.
    if key == b"\x1b":
        if buffer:
            new_rows, new_cursor = _rebuild_rows_with_query(
                original_model, "", None,
            )
            return new_rows, new_cursor, "", "EDITING", None, False
        return rows, cursor, buffer, "NORMAL", None, False

    # Backspace / DEL: drop the last char (no-op on empty).
    if key in (b"\x7f", b"\b"):
        if not buffer:
            return rows, cursor, buffer, "EDITING", None, False
        new_buffer = buffer[:-1]
        prev = _session_at_cursor(rows, cursor)
        new_rows, new_cursor = _rebuild_rows_with_query(
            original_model, new_buffer, prev,
        )
        return new_rows, new_cursor, new_buffer, "EDITING", None, False

    # Move up / down without touching the buffer.
    if key == b"\x1b[A" or key in (b"k", b"K"):
        return _move(rows, cursor, -1, "EDITING") + (buffer, "EDITING", None, False)
    if key == b"\x1b[B" or key in (b"j", b"J"):
        return _move(rows, cursor, +1, "EDITING") + (buffer, "EDITING", None, False)

    # Printable: append to the buffer (q/Q/slash are literal here so
    # the user can search for them), then rebuild.
    if len(key) == 1 and 32 <= key[0] < 127:
        ch = key.decode("utf-8", errors="replace")
        new_buffer = buffer + ch
        prev = _session_at_cursor(rows, cursor)
        new_rows, new_cursor = _rebuild_rows_with_query(
            original_model, new_buffer, prev,
        )
        return new_rows, new_cursor, new_buffer, "EDITING", None, False

    # Unknown key: no-op.
    return rows, cursor, buffer, "EDITING", None, False


def pick_session(model: list[WorktreeInfo]) -> Session | None:
    """Run the inline arrow-key picker. Returns the selected Session, or
    None if the user quit (``q`` / ``Esc`` / ``Ctrl-C``). Always restores
    the original ``termios`` state on exit, even on exception.

    Live search: ``/`` enters EDITING (in-place buffer), printable
    characters enter EDITING with the buffer seeded with that char,
    and ``q``/``Q``/``/`` are literal characters while EDITING
    (so they narrow the search, not quit). ``Esc`` is a two-phase
    clear: with a non-empty buffer it just clears the buffer (stays
    in EDITING); with an empty buffer it returns to NORMAL.

    The bulk of the per-key logic lives in the pure helpers
    :func:`_step_normal` and :func:`_step_editing` so it can be unit
    tested without a TTY.
    """
    rows = build_rows(model)
    selectable = _selectable_indices(rows)
    if not selectable:
        return None

    # Keep the unfiltered model so an "Esc" with a non-empty buffer
    # can rebuild rows from scratch (clearing the buffer == back to
    # the full model the picker started with).
    original_model = list(model)
    total_sessions = sum(1 for r in rows if r["kind"] == "session")
    cursor = selectable[0]
    scroll = 0
    buffer = ""
    mode = "NORMAL"  # "NORMAL" | "EDITING"

    try:
        saved = termios.tcgetattr(0)
    except termios.error:
        saved = None

    try:
        if saved is not None:
            attrs = termios.tcgetattr(0)
            # Disable canonical mode + echo, but keep ISIG so Ctrl-C
            # still raises KeyboardInterrupt (which the outer try/except
            # catches and turns into a clean None return).
            attrs[3] &= ~(termios.ICANON | termios.ECHO)
            termios.tcsetattr(0, termios.TCSAFLUSH, attrs)

        while True:
            max_x, max_y = _terminal_size()
            max_y = max(5, max_y)
            _render_picker(sys.stdout, rows, cursor, scroll, max_x, max_y,
                           query=buffer, total_sessions=total_sessions)

            key = _read_key(0.5)
            if not key:
                continue

            if mode == "NORMAL":
                new_rows, new_cursor, new_buffer, new_mode, returned, should_exit = _step_normal(
                    key, rows, cursor, buffer, original_model,
                )
            else:
                new_rows, new_cursor, new_buffer, new_mode, returned, should_exit = _step_editing(
                    key, rows, cursor, buffer, original_model,
                )

            rows = new_rows
            cursor = new_cursor
            buffer = new_buffer
            mode = new_mode

            if should_exit:
                if returned is _RAISE:
                    raise KeyboardInterrupt
                return returned

            body_h = max(1, max_y - 2)
            if cursor < scroll:
                scroll = cursor
            elif cursor >= scroll + body_h:
                scroll = cursor - body_h + 1

    except KeyboardInterrupt:
        return None
    finally:
        if saved is not None:
            try:
                termios.tcsetattr(0, termios.TCSAFLUSH, saved)
            except termios.error:
                pass
        sys.stdout.write(_ANSI["show_cur"] + "\n")
        sys.stdout.flush()
