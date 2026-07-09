"""Trap fixture: parameterless hash with a long, named constant.

This is a FALSE POSITIVE trap. The literal `64` is the SHA-256 output
length in hex characters; the constant is named, the use is correct,
and the surrounding code is safe. A noisy scanner might flag the
"magic number" but the constant is already extracted.

EXPECTED: `/dev-kit:security` MUST NOT flag (safe, no false positives).
"""

HEX_CHARS_PER_SHA256_DIGEST = 64


def hex_truncated_sha256(payload: bytes) -> str:
    import hashlib
    digest = hashlib.sha256(payload).hexdigest()
    return digest[:HEX_CHARS_PER_SHA256_DIGEST]
