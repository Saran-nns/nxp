"""
NXP Binary Frame Protocol (BFP) — Complete Implementation
==========================================================
A universal binary codec covering ALL NXP frame types:

  Skill / Tool calls    → struct header + msgpack body
  Replies               → struct header + msgpack body
  Error frames          → struct header + uint16 error code (+ optional msg)
  Streaming chunks      → struct header + raw bytes
  Binary blobs          → two-frame: metadata + raw bytes
  Agent card / handshake→ hash-based dedup + JSON fallback

Frame wire format (all frames start with a 4-byte header):
  [type: 1B][seq: 3B][...type-specific fields...][body: NB]

This module is transport-agnostic — it works over WebSocket, TCP, or UNIX sockets.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import os
import struct
from typing import Any

import msgpack

# ─── Frame Type Registry ─────────────────────────────────────────────────────
#
# 1-byte type tags.  High bit 0 = client→server.  High bit 1 = server→client.
# This lets routers make forwarding decisions without parsing the full frame.

CALL       = 0x01   # Skill call (client → server)
TOOL       = 0x02   # Tool call — same wire format as CALL, different semantic
REPLY      = 0x10   # Skill/tool reply (server → client)
STREAM     = 0x11   # Streaming chunk (server → client, or bidirectional)
ERROR      = 0x12   # Error frame  — binary error code + optional UTF-8 detail
ZCD_DELTA  = 0x13   # Zero-Copy Delta state frame (ultra-fast sub-agent delta)
BLOB_META  = 0x20   # Binary blob metadata (precedes BLOB_DATA)
BLOB_DATA  = 0x21   # Raw binary payload (image, audio, embedding bytes)
CARD_REQ   = 0x30   # Client sends 8-byte hash of last known agent card
CARD_HIT   = 0x31   # Server: "card unchanged" — 1 byte, saves full retransmit
CARD_FULL  = 0x32   # Server sends full agent card JSON (first connect or cache miss)
HANDSHAKE  = 0x40   # Auth handshake — always JSON NexusFrame (full interop)
PING       = 0x50
PONG       = 0x51

TYPE_NAMES = {
    CALL: "CALL", TOOL: "TOOL", REPLY: "REPLY", STREAM: "STREAM",
    ERROR: "ERROR", ZCD_DELTA: "ZCD_DELTA", BLOB_META: "BLOB_META", BLOB_DATA: "BLOB_DATA",
    CARD_REQ: "CARD_REQ", CARD_HIT: "CARD_HIT", CARD_FULL: "CARD_FULL",
    HANDSHAKE: "HANDSHAKE", PING: "PING", PONG: "PONG",
}

# ─── Error Code Registry ─────────────────────────────────────────────────────
#
# Binary error codes (uint16) replace verbose JSON error strings on the wire.
# Full human-readable messages are looked up client-side from this registry.
# New codes can be registered at runtime without protocol changes.

ERR_OK              = 0x0000
ERR_SKILL_NOT_FOUND = 0x0001
ERR_TOOL_NOT_FOUND  = 0x0002
ERR_AUTH_FAILED     = 0x0003
ERR_INVALID_ARGS    = 0x0004
ERR_TIMEOUT         = 0x0005
ERR_RATE_LIMITED    = 0x0006
ERR_INTERNAL        = 0x0007
ERR_STREAM_ENDED    = 0x0008
ERR_BLOB_TOO_LARGE  = 0x0009
ERR_REPLAY_DETECTED = 0x000A
ERR_UNKNOWN         = 0xFFFF

ERROR_REGISTRY: dict[int, str] = {
    ERR_OK:              "OK",
    ERR_SKILL_NOT_FOUND: "Skill not found",
    ERR_TOOL_NOT_FOUND:  "Tool not found",
    ERR_AUTH_FAILED:     "Authentication failed",
    ERR_INVALID_ARGS:    "Invalid arguments",
    ERR_TIMEOUT:         "Execution timeout",
    ERR_RATE_LIMITED:    "Rate limit exceeded",
    ERR_INTERNAL:        "Internal server error",
    ERR_STREAM_ENDED:    "Stream ended unexpectedly",
    ERR_BLOB_TOO_LARGE:  "Blob payload exceeds limit",
    ERR_REPLAY_DETECTED: "Replay attack detected",
    ERR_UNKNOWN:         "Unknown error",
}

# Content-type codes for BLOB frames
BLOB_JPEG   = 0x01
BLOB_PNG    = 0x02
BLOB_AUDIO  = 0x03
BLOB_FLOAT32= 0x04   # numpy / embedding vector
BLOB_BYTES  = 0xFF   # raw bytes, unspecified type

# ─── Codec Helpers ───────────────────────────────────────────────────────────

_SEQ3 = struct.Struct('>I')  # pack seq as 4B big-endian, slice to 3B

def _enc_seq(seq: int) -> bytes:
    """Encode a 24-bit sequence number into 3 bytes."""
    return (seq & 0xFFFFFF).to_bytes(3, 'big')

def _dec_seq(b: bytes) -> int:
    """Decode a 3-byte big-endian sequence number."""
    return int.from_bytes(b[:3], 'big')

def _mp_pack(obj: Any) -> bytes:
    return msgpack.packb(obj, use_bin_type=True)

def _mp_unpack(data: bytes) -> Any:
    return msgpack.unpackb(data, raw=False)


# ─── Frame Encoders ──────────────────────────────────────────────────────────

def encode_call(seq: int, skill_idx: int, kwargs: dict,
                auth4: bytes = b'\x00\x00\x00\x00') -> bytes:
    """
    CALL / TOOL frame.
    Wire: [0x01][seq:3B][skill_idx:2B][auth:4B][msgpack(kwargs)]
    Total fixed overhead: 10 bytes (vs ~55 bytes JSON + session_id)
    """
    return (
        bytes([CALL])
        + _enc_seq(seq)
        + struct.pack('>H', skill_idx)
        + auth4[:4]
        + _mp_pack(kwargs)
    )


def encode_tool(seq: int, tool_idx: int, kwargs: dict,
                auth4: bytes = b'\x00\x00\x00\x00') -> bytes:
    """Tool call — identical layout to CALL but type byte = TOOL."""
    return (
        bytes([TOOL])
        + _enc_seq(seq)
        + struct.pack('>H', tool_idx)
        + auth4[:4]
        + _mp_pack(kwargs)
    )


def encode_reply(seq: int, result: Any) -> bytes:
    """
    REPLY frame.
    Wire: [0x10][seq:3B][msgpack(result)]
    For scalar int result: 4 + 1 = 5 bytes total.
    """
    return bytes([REPLY]) + _enc_seq(seq) + _mp_pack(result)


def encode_error(seq: int, error_code: int, detail: str = "") -> bytes:
    """
    ERROR frame.
    Wire: [0x12][seq:3B][error_code:2B][optional utf-8 detail]
    Common errors (known code, no detail): 6 bytes.
    vs JSON error frame: ~40 bytes.
    """
    base = bytes([ERROR]) + _enc_seq(seq) + struct.pack('>H', error_code)
    return base + detail.encode('utf-8') if detail else base


def encode_zcd_delta(seq: int, delta_idx: int, data: bytes) -> bytes:
    """
    ZCD_DELTA — Zero-Copy Delta frame for sub-agent token streaming and state diffs.
    Wire: [0x13][seq:3B][delta_idx:1B][data:NB]
    Overhead: 5 bytes only.
    """
    return (
        bytes([ZCD_DELTA])
        + _enc_seq(seq)
        + struct.pack('>B', delta_idx)
        + data
    )


def encode_stream(seq: int, chunk_seq: int, data: bytes,
                  is_final: bool = False) -> bytes:
    """
    STREAM chunk frame.
    Wire: [0x11][seq:3B][chunk_seq:2B][flags:1B][data]
    flags: bit 0 = is_final
    Fixed overhead: 7 bytes per chunk.
    """
    flags = 0x01 if is_final else 0x00
    return (
        bytes([STREAM])
        + _enc_seq(seq)
        + struct.pack('>HB', chunk_seq, flags)
        + data
    )


def encode_blob_meta(seq: int, total_len: int, content_type: int,
                     meta: dict | None = None) -> bytes:
    """
    BLOB_META frame — announces an incoming binary blob.
    Wire: [0x20][seq:3B][total_len:4B][content_type:1B][msgpack(meta)]
    Fixed overhead: 9 bytes.
    """
    base = (
        bytes([BLOB_META])
        + _enc_seq(seq)
        + struct.pack('>IB', total_len, content_type)
    )
    return base + (_mp_pack(meta) if meta else b'')


def encode_blob_data(seq: int, data: bytes) -> bytes:
    """
    BLOB_DATA frame — raw binary payload (no encoding).
    Wire: [0x21][seq:3B][raw bytes]
    Overhead: 4 bytes only — matches raw WebSocket binary frame overhead.
    """
    return bytes([BLOB_DATA]) + _enc_seq(seq) + data


def encode_card_req(card_hash: bytes) -> bytes:
    """
    CARD_REQ — client sends 8-byte hash of its cached agent card.
    If the server's card matches, it replies with CARD_HIT (1 byte).
    Wire: [0x30][hash:8B] = 9 bytes total.
    """
    return bytes([CARD_REQ]) + card_hash[:8]


def encode_card_hit() -> bytes:
    """CARD_HIT — server says 'your cached card is still current'. 1 byte."""
    return bytes([CARD_HIT])


def encode_card_full(card_json: str) -> bytes:
    """CARD_FULL — server sends full agent card as JSON (UTF-8)."""
    return bytes([CARD_FULL]) + card_json.encode('utf-8')


def encode_ping(seq: int) -> bytes:
    return bytes([PING]) + _enc_seq(seq)

def encode_pong(seq: int) -> bytes:
    return bytes([PONG]) + _enc_seq(seq)


# ─── Frame Decoders ──────────────────────────────────────────────────────────

class BFPFrame:
    """Decoded BFP frame."""
    __slots__ = ('type', 'seq', 'skill_idx', 'tool_idx', 'auth4',
                 'kwargs', 'result', 'error_code', 'error_detail',
                 'chunk_seq', 'is_final', 'data',
                 'total_len', 'content_type', 'meta',
                 'card_hash', 'card_json', 'raw')

    def __init__(self):
        for s in self.__slots__:
            object.__setattr__(self, s, None)

    def __repr__(self):
        name = TYPE_NAMES.get(self.type, f"0x{self.type:02x}")
        return f"BFPFrame(type={name}, seq={self.seq})"


def decode(raw: bytes) -> BFPFrame:
    """
    Decode any BFP frame from raw bytes.
    Dispatch is O(1) — single byte lookup, no string parsing.
    """
    f = BFPFrame()
    f.raw = raw
    f.type = raw[0]
    f.seq = _dec_seq(raw[1:4])

    t = f.type

    if t == CALL or t == TOOL:
        # [type:1][seq:3][skill_idx:2][auth:4][body:N]
        f.skill_idx = struct.unpack('>H', raw[4:6])[0]
        f.tool_idx  = f.skill_idx
        f.auth4     = raw[6:10]
        f.kwargs    = _mp_unpack(raw[10:])

    elif t == REPLY:
        # [type:1][seq:3][body:N]
        f.result = _mp_unpack(raw[4:])

    elif t == ERROR:
        # [type:1][seq:3][error_code:2][optional detail:N]
        f.error_code   = struct.unpack('>H', raw[4:6])[0]
        f.error_detail = raw[6:].decode('utf-8') if len(raw) > 6 else \
                         ERROR_REGISTRY.get(f.error_code, "Unknown error")

    elif t == STREAM:
        # [type:1][seq:3][chunk_seq:2][flags:1][data:N]
        f.chunk_seq, flags = struct.unpack('>HB', raw[4:7])
        f.is_final = bool(flags & 0x01)
        f.data     = raw[7:]

    elif t == BLOB_META:
        # [type:1][seq:3][total_len:4][content_type:1][meta_msgpack:N]
        f.total_len, f.content_type = struct.unpack('>IB', raw[4:9])
        f.meta = _mp_unpack(raw[9:]) if len(raw) > 9 else {}

    elif t == BLOB_DATA:
        # [type:1][seq:3][raw bytes]
        f.data = raw[4:]

    elif t == CARD_REQ:
        f.card_hash = raw[1:9]  # 8-byte hash (no seq on card req)

    elif t == CARD_FULL:
        f.card_json = raw[1:].decode('utf-8')

    # CARD_HIT, PING, PONG — no payload beyond seq

    return f


# ─── SDMT Auth Helper ─────────────────────────────────────────────────────────
# Sequence-Derived Micro-Token: 4-byte HMAC(session_key, seq)
# Replaces 16-char session_id on the hot path.

def sdmt_auth(session_key: bytes, seq: int) -> bytes:
    """Compute 4-byte SDMT auth token for this call sequence number."""
    return hmac_mod.new(
        session_key, seq.to_bytes(4, 'little'), hashlib.sha256
    ).digest()[:4]

def sdmt_verify(session_key: bytes, seq: int, auth4: bytes) -> bool:
    """Verify SDMT auth token in constant time."""
    expected = sdmt_auth(session_key, seq)
    return hmac_mod.compare_digest(expected, bytes(auth4))


# ─── Card Hash Helper ─────────────────────────────────────────────────────────

def card_hash(card_json: str) -> bytes:
    """Compute 8-byte hash of an agent card for cache deduplication."""
    return hashlib.blake2b(card_json.encode(), digest_size=8).digest()
