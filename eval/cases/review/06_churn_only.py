"""Sample review case: no value (VM-1, VM-2, VM-4).

A pure rename + import reorder with no semantic change. The diff adds
zero user value: nothing breaks, nothing improves, nothing the user
can perceive has changed. The reviewer should call this out (or
explicitly Approve with a value-comment).

EXPECTED: `/dev-kit:review` MUST return Approve AND include a value
comment ("churn-only; no user-impacting change").
"""


# Before: from foo.bar import compute_total
# After:  from foo.bar import compute_total as _compute_total
# Then renamed every call site from `compute_total(...)` to
# `_compute_total(...)`. No behavior change, no bug fix, no perf win.
import json  # before: this import was sorted first; now last.


def process(payload):
    data = json.loads(payload)
    total = _compute_total(data["items"])
    return {"total": total, "n": len(data["items"])}


def _compute_total(items):
    return sum(item["price"] * item["qty"] for item in items)
