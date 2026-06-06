# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fork #331 follow-up (@Gusdezup): Kobo sync fails behind reverse proxies
with default buffer sizes. Measured root cause: the x-kobo-synctoken
response header. Our own cursor fields are ~495B, but with Kobo store
proxying enabled the store's 3-part JWT (~2-2.5KB real-world, see
notes/KOBO-PROTOCOL-REFERENCE.md §3.1) is embedded in our JSON and then
base64'd AGAIN (+33% on the largest component) — pushing total response
headers past nginx's 4K default (`proxy_buffer_size`).

Fix: transport-level compression of the token. build_sync_token emits
`z1:` + b64(zlib(json)); from_headers sniffs the prefix and falls back to
the legacy plain-b64 parse for tokens already in the wild. Devices echo
the token opaquely — only this server parses it — so no device migration
exists. The schema VERSION is untouched (compression is transport, not
schema).

Sniff safety: the b64 alphabet (A-Za-z0-9+/=) contains neither ':' nor
'.', so `z1:`-prefixed tokens can't collide with legacy b64 tokens, and
the existing dotted kobo-store-token path ('.' in token) stays reachable.
"""

import json
import random
import zlib
from base64 import b64decode, b64encode
from datetime import datetime

import pytest

from cps.services.SyncToken import SyncToken, to_epoch_timestamp


def _legacy_header(data: dict) -> str:
    """Build a token exactly the way pre-#331 servers did (plain b64 JSON)."""
    return b64encode(json.dumps(
        {"version": "1-4-0", "data": data}).encode()).decode()


def _data(store_token=""):
    now = datetime(2026, 6, 7, 1, 0, 0)
    return {
        "raw_kobo_store_token": store_token,
        "books_last_modified": to_epoch_timestamp(now),
        "books_last_created": to_epoch_timestamp(now),
        "archive_last_modified": to_epoch_timestamp(now),
        "reading_state_last_modified": to_epoch_timestamp(now),
        "tags_last_modified": to_epoch_timestamp(now),
        "books_last_id": 42,
        "magic_shelf_last_id": 7,
        "magic_shelf_membership_at": to_epoch_timestamp(now),
    }


def _fake_store_jwt(size=2400):
    """Synthetic 3-part JWT shaped like the real store token (b64ish text)."""
    part = b64encode(b"x" * (size // 2)).decode()
    return "eyJhbGciOiJSUzI1NiJ9." + part[:size - 60] + ".sig"


def _fake_store_jwt_high_entropy(size=2400):
    """Like _fake_store_jwt but with seeded-random payload bytes. Real store
    JWTs are b64 of cryptographic material — near-maximal entropy — so zlib
    only recovers the 8->6-bit b64 repacking (~25%), not the ~10x a run of
    'x' gives. This is the worst realistic case for the header budget."""
    rnd = random.Random(331)
    raw = rnd.getrandbits(size * 8).to_bytes(size, "big")
    part = b64encode(raw).decode()
    return "eyJhbGciOiJSUzI1NiJ9." + part[:size - 60] + ".sig"


@pytest.mark.unit
class TestLegacyTokensStillParse:
    def test_legacy_plain_b64_parses_with_all_fields(self):
        """Tokens already on devices in the wild MUST keep parsing."""
        header = _legacy_header(_data(store_token="abc"))
        tok = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: header})
        assert tok.books_last_id == 42
        assert tok.magic_shelf_last_id == 7
        assert tok.raw_kobo_store_token == "abc"

    def test_dotted_store_token_passthrough_unchanged(self):
        header = "storepart1.storepart2"
        tok = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: header})
        assert tok.raw_kobo_store_token == header


@pytest.mark.unit
class TestCompressedTokens:
    def test_round_trip(self):
        src = SyncToken(
            raw_kobo_store_token=_fake_store_jwt(),
            books_last_id=42,
            magic_shelf_last_id=7,
        )
        header = src.build_sync_token()
        assert header.startswith("z1:"), (
            "build_sync_token must emit the compressed transport format"
        )
        out = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: header})
        assert out.books_last_id == 42
        assert out.magic_shelf_last_id == 7
        assert out.raw_kobo_store_token == src.raw_kobo_store_token

    @pytest.mark.parametrize(
        "make_jwt", [_fake_store_jwt, _fake_store_jwt_high_entropy],
        ids=["compressible", "high-entropy"])
    def test_oversized_store_token_fits_4k_budget(self, make_jwt):
        """The reporter-mirror case: a realistic ~2.4KB store JWT must leave
        the whole header value comfortably inside nginx's 4K default once
        cookies (~300B) + CSP (~140B) + the rest (~400B) are accounted
        for. Budget: token value < 3000 bytes. The high-entropy variant is
        the one that actually exercises the boundary (~2650B measured) —
        real JWTs barely compress, so a regression that bloats the encoding
        for incompressible input fails here first."""
        src = SyncToken(raw_kobo_store_token=make_jwt(2400))
        header = src.build_sync_token()
        assert len(header) < 3000, (
            f"compressed token is {len(header)}B — must stay under the 3000B "
            "budget so total response headers fit nginx's 4K default"
        )

    def test_compression_beats_legacy_encoding(self):
        src = SyncToken(raw_kobo_store_token=_fake_store_jwt(2400))
        compressed = src.build_sync_token()
        legacy = b64encode(json.dumps(
            {"version": SyncToken.VERSION, "data": _data(_fake_store_jwt(2400))}
        ).encode()).decode()
        assert len(compressed) < len(legacy) * 0.75, (
            "compression must beat the legacy double-b64 encoding by a "
            "meaningful margin"
        )

    def test_garbage_after_marker_degrades_to_fresh_token(self):
        tok = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: "z1:!!!notb64!!!"})
        assert tok.books_last_id == -1
        assert tok.books_last_modified == datetime.min

    def test_truncated_compressed_token_degrades_cleanly(self):
        """A proxy that truncates the header (the original failure class)
        must yield a fresh token, not a 500."""
        src = SyncToken(raw_kobo_store_token=_fake_store_jwt())
        header = src.build_sync_token()
        tok = SyncToken.from_headers({SyncToken.SYNC_TOKEN_HEADER: header[:len(header) // 2]})
        assert tok.books_last_modified == datetime.min

    def test_decompression_amplification_is_bounded(self):
        """CWE-409 (improper handling of highly compressed data): the header
        is attacker-suppliable, so expansion must be capped. A payload small
        enough to pass the 16KB compressed pre-filter but decompressing past
        the 64KB cap must degrade to a fresh token instead of being
        expanded in full. (Highly repetitive input compresses far below the
        pre-filter while decompressing well past the cap.)"""
        oversized = b64encode(zlib.compress(b"\x00" * (256 * 1024), 9)).decode()
        assert len(oversized) < SyncToken.MAX_COMPRESSED_B64, (
            "fixture must pass the pre-filter to exercise the "
            "decompression cap")
        tok = SyncToken.from_headers(
            {SyncToken.SYNC_TOKEN_HEADER: "z1:" + oversized})
        assert tok.books_last_modified == datetime.min
        assert tok.books_last_id == -1

    def test_oversized_compressed_payload_rejected_by_prefilter(self):
        """Anything past 16KB of b64 payload is rejected before
        decompression is even attempted."""
        big = "A" * (SyncToken.MAX_COMPRESSED_B64 + 100)
        tok = SyncToken.from_headers(
            {SyncToken.SYNC_TOKEN_HEADER: "z1:" + big})
        assert tok.books_last_modified == datetime.min

    def test_real_tokens_fit_far_under_the_caps(self):
        """The caps must never bite legitimate traffic: a realistic token
        with a fat store JWT sits an order of magnitude under both."""
        src = SyncToken(raw_kobo_store_token=_fake_store_jwt(2400))
        header = src.build_sync_token()
        payload = header[len(SyncToken.COMPRESSED_PREFIX):]
        assert len(payload) < SyncToken.MAX_COMPRESSED_B64 / 4
        raw = zlib.decompress(b64decode(payload))
        assert len(raw) < SyncToken.MAX_DECOMPRESSED / 8

    def test_schema_version_untouched(self):
        """Compression is transport-level: the inner schema VERSION must
        stay 1-4-0 so version-gated logic is unaffected."""
        assert SyncToken.VERSION == "1-4-0"
        src = SyncToken(books_last_id=1)
        header = src.build_sync_token()
        raw = zlib.decompress(b64decode(header[3:]))
        assert json.loads(raw)["version"] == "1-4-0"
