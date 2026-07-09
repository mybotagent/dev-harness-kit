"""Sample security case: IDOR (OWASP A01:2025 Broken Access Control).

A user-controlled `user_id` is used to fetch a record WITHOUT checking
that the requester is authorized to view it. A horizontal-privilege
escalation: any logged-in user can read any other user's profile by
incrementing the `user_id` query parameter.

EXPECTED: `/dev-kit:security` MUST flag as A01 (Broken Access Control),
severity major or higher.
"""


def get_user_profile(request, db):
    user_id = request.GET["user_id"]  # user-controlled
    # BUG: no check that request.user.id == int(user_id) or that the
    # requester has admin rights to view this profile.
    return db.execute(
        "SELECT id, email, role FROM users WHERE id = %s", (user_id,)
    ).fetchone()
