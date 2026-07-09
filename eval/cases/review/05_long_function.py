"""Sample review case: clean-code violation (CC-2).

A 60+ line function with 5 parameters and mixed concerns (parse, fetch,
validate, transform, format). The body has clear sub-sections that
should be extracted.

EXPECTED: `/dev-kit:review` MUST flag at least one `correctness` minor
or higher finding about function size and parameter count.
"""


def process_user_submission(
    raw_payload, current_user, request_ip, user_agent, db
):
    # 1. parse
    if not raw_payload:
        return {"error": "empty"}
    try:
        data = __import__("json").loads(raw_payload)
    except ValueError:
        return {"error": "bad json"}
    # 2. fetch
    user_row = db.execute(
        "SELECT id, tier FROM users WHERE id = %s", (current_user.id,)
    ).fetchone()
    if not user_row:
        return {"error": "no such user"}
    # 3. validate
    if "title" not in data or not isinstance(data["title"], str):
        return {"error": "title required"}
    if len(data["title"]) > 200:
        return {"error": "title too long"}
    # 4. transform
    normalized = {
        "title": data["title"].strip(),
        "body": data.get("body", "").strip(),
        "tags": [t.lower() for t in data.get("tags", []) if isinstance(t, str)],
    }
    # 5. format
    record = {
        "id": user_row["id"],
        "title": normalized["title"],
        "body": normalized["body"],
        "tags": normalized["tags"],
        "ip": request_ip,
        "ua": user_agent,
        "tier": user_row["tier"],
    }
    return {"ok": True, "record": record}
