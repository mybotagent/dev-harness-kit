"""Sample security case: SQL injection (OWASP A05:2025 Injection).

A raw f-string interpolates user input into a SQL query. Trivially
exploitable: any caller can pass `' OR 1=1 --` and dump the table.

EXPECTED: `/dev-kit:security` MUST flag as A05 (Injection),
severity critical.
"""


def find_user(name, db):
    # BUG: f-string SQL = classic SQL injection.
    return db.execute(
        f"SELECT id, email FROM users WHERE name = '{name}'"
    ).fetchall()
