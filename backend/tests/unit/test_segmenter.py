import pytest

from app.simulation.segmenter import segment_message


def test_empty_message_yields_no_segments():
    assert segment_message("", mss_bytes=10) == []


def test_message_smaller_than_mss_is_one_segment():
    segments = segment_message("HELLO", mss_bytes=10)
    assert len(segments) == 1
    assert segments[0].payload == b"HELLO"
    assert segments[0].byte_offset == 0
    assert segments[0].index == 0


def test_message_divides_evenly():
    segments = segment_message("ABCDEFGHI", mss_bytes=3)
    assert [s.payload for s in segments] == [b"ABC", b"DEF", b"GHI"]
    assert [s.byte_offset for s in segments] == [0, 3, 6]
    assert [s.index for s in segments] == [0, 1, 2]


def test_message_divides_unevenly_last_segment_is_short():
    segments = segment_message("HELLO TCP NETWORK", mss_bytes=5)
    assert len(segments) == 4
    assert b"".join(s.payload for s in segments) == b"HELLO TCP NETWORK"
    assert len(segments[-1].payload) <= 5


def test_offsets_and_reassembly_are_consistent():
    message = "The quick brown fox jumps over the lazy dog"
    segments = segment_message(message, mss_bytes=7)
    reassembled = b"".join(s.payload for s in segments)
    assert reassembled == message.encode("utf-8")
    # Each offset should equal the running sum of prior payload lengths.
    running = 0
    for s in segments:
        assert s.byte_offset == running
        running += len(s.payload)


def test_invalid_mss_raises():
    with pytest.raises(ValueError):
        segment_message("hi", mss_bytes=0)


def test_multibyte_utf8_message_splits_on_bytes_not_chars():
    # Ensures we split the UTF-8 *byte* stream (documented behavior), even
    # though this can in principle split a multi-byte character across
    # segments -- acceptable for this simulator's purposes.
    message = "caf\u00e9"  # 'caf\xc3\xa9' -> 5 bytes in UTF-8
    encoded = message.encode("utf-8")
    segments = segment_message(message, mss_bytes=3)
    assert b"".join(s.payload for s in segments) == encoded
