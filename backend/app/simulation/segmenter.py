"""Splits an application-layer message into MSS-sized segments.

This is intentionally pure/stateless: given a message and an MSS, produce
a deterministic list of `Segment`s with byte offsets. The caller (session)
is responsible for turning each `Segment` into a `Packet` with the correct
sequence number (offset + initial_send_seq).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Segment:
    index: int
    """0-based order of this segment within the message."""
    byte_offset: int
    """Offset of this segment's first byte within the encoded message."""
    payload: bytes


def segment_message(message: str, mss_bytes: int) -> List[Segment]:
    """Split `message` (UTF-8 encoded) into segments no larger than
    `mss_bytes`. Handles empty messages (zero segments) and messages that
    divide evenly or unevenly into MSS-sized chunks.
    """
    if mss_bytes <= 0:
        raise ValueError("mss_bytes must be > 0")

    encoded = message.encode("utf-8")
    if not encoded:
        return []

    segments: List[Segment] = []
    offset = 0
    index = 0
    while offset < len(encoded):
        chunk = encoded[offset: offset + mss_bytes]
        segments.append(Segment(index=index, byte_offset=offset, payload=chunk))
        offset += len(chunk)
        index += 1
    return segments
