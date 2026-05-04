"""Tests for PKCE code-verifier and code-challenge generation."""

import base64
import hashlib
import re

from etsy_mcp.auth import generate_pkce_pair


def test_verifier_length_and_charset():
    verifier, _ = generate_pkce_pair()
    # RFC 7636: 43-128 chars, [A-Z][a-z][0-9]-._~
    assert 43 <= len(verifier) <= 128
    assert re.fullmatch(r"[A-Za-z0-9\-._~]+", verifier)


def test_challenge_is_s256_of_verifier():
    verifier, challenge = generate_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert challenge == expected


def test_pairs_are_unique():
    pairs = {generate_pkce_pair()[0] for _ in range(50)}
    assert len(pairs) == 50  # cryptographically vanishing chance of collision
