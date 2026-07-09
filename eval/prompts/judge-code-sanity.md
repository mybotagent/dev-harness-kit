# Code-Sanity Rubric (judge-code-sanity, v2.0.0)

Shared 20-checkbox rubric used by the `review` judge for the
`code_sanity_score` axis. The reviewer embeds this checklist when
scoring a fixture; the LLM returns three sub-scores (0-10 each) and the
runner computes the composite as `0.4*clean + 0.4*over_eng + 0.2*value`.

The reviewer must apply each item ONLY when the relevant pattern is
present in the input. Score a sub-rubric by `(items_flagged /
items_present_in_input) * 10`. If no item from a sub-rubric applies to
the input, score that sub-rubric at 10 (vacuously perfect — there is
nothing wrong to flag).

## Clean code (8 items)

CC-1. Vague or short names (`x`, `tmp`, `data`, `val`, `obj`,
      `foo`, `bar`, `do_thing`).
CC-2. Function > 50 lines OR > 4 parameters.
CC-3. Dead code: unused imports, commented-out blocks, unreachable
      branches, `pass` placeholders left in.
CC-4. Magic numbers or hardcoded strings without named constants
      (e.g. literal `0.95` where `CONFIDENCE_THRESHOLD` is expected).
CC-5. Copy-paste duplication: the same logic in 2+ places without
      extraction.
CC-6. Bare `except` / swallowed errors / missing `finally` or
      cleanup. Examples: `except: pass`, `except Exception: return None`
      with no log.
CC-7. Type unsafety: `any`, missing return types, dynamic `getattr`
      chains, `dict` instead of a typed model.
CC-8. Stale or misleading comments: comment says X but code does Y;
      references to removed functions; TODO/FIXME left in shipped code.

## Over-engineering (8 items)

OE-1. Interface / abstract base class with exactly one implementer.
OE-2. Speculative parameters or configs for hypothetical use
      (`enable_legacy_mode=False` when there is no legacy).
OE-3. Premature optimization without measurement
      (caching layers with no profile data, hand-rolled pooling).
OE-4. YAGNI: features, flags, or extension points for hypothetical
      futures that are not requested.
OE-5. Excessive layering: 3+ abstraction layers for trivial logic
      (e.g. controller -> service -> manager -> repository for a
      one-table CRUD).
OE-6. Factory / Strategy / DI container for a single implementation
      with no second impl in sight.
OE-7. Deep inheritance (3+ levels) without polymorphism payoff.
OE-8. 1-class-per-file pattern without justification; file count
      wildly exceeds the conceptual surface area.

## Value / meaning (4 items)

VM-1. Change has a stated purpose tied to a real user need (visible
      in commit message, PR description, or docstring). Pure
      refactor with no user impact still has value if named.
VM-2. Not noise / cosmetic / churn (whitespace-only, rename
      churn, import reorder with no semantic change).
VM-3. Scope matches the problem (no creep, no unrelated drive-by
      edits, no bundling multiple features).
VM-4. The diff earns its lines: every block of changed code
      contributes to the stated purpose. No "while I was here"
      additions.
