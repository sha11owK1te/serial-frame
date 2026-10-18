import math
import random
import unittest

from serial_frame import FrameParser, build_frame
from tests.test_codec import FakeClock


class TestBoundaries(unittest.TestCase):
    def test_all_lengths_and_split_points(self):
        for length in range(256):
            payload = bytes(range(length))
            frame = build_frame(payload)
            for split in range(len(frame) + 1):
                p = FrameParser()
                got = p.feed(frame[:split]) + p.feed(frame[split:])
                self.assertEqual(got, [payload], (length, split))
                self.assertEqual(p.pending, 0)

    def test_seeded_chunking_and_accounting(self):
        rng = random.Random(42)
        expected = [bytes(rng.randrange(256) for _ in range(rng.randrange(256)))
                    for _ in range(200)]
        bad = bytearray(build_frame(b"broken"))
        bad[-1] ^= 1
        stream = b"\x00\x13" + bad + b"".join(map(build_frame, expected))
        for trial in range(20):
            p, got, offset = FrameParser(), [], 0
            while offset < len(stream):
                size = rng.randrange(1, 300)
                got.extend(p.feed(stream[offset:offset + size]))
                offset += size
                self.assertLess(p.pending, 260)
            self.assertEqual(got, expected, trial)
            self.assertEqual(p.crc_errors, 1)
            self.assertEqual(p.discarded, 2 + len(bad))
            self.assertEqual(p.discarded + sum(len(x) + 5 for x in got), len(stream))

    def test_garbage_does_not_create_timeout(self):
        clock = FakeClock()
        p = FrameParser(timeout_ms=50, clock=clock)
        p.feed(b"\x00\x13")
        self.assertEqual(p.pending, 0)
        self.assertEqual(p.discarded, 2)
        clock.advance(60)
        self.assertEqual(p.tick(), 0)
        self.assertEqual(p.timeouts, 0)

    def test_replaced_header_gets_new_deadline(self):
        clock = FakeClock()
        p = FrameParser(timeout_ms=50, clock=clock)
        p.feed(b"\xaa")
        clock.advance(40)
        p.feed(b"\xaa")
        clock.advance(20)
        frame = build_frame(b"ok")
        self.assertEqual(p.feed(frame[1:]), [b"ok"])
        self.assertEqual(p.timeouts, 0)
        self.assertEqual(p.discarded, 1)

    def test_invalid_timeout(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                FrameParser(timeout_ms=value)

    def test_invalid_feed_does_not_expire_state(self):
        clock = FakeClock()
        p = FrameParser(timeout_ms=50, clock=clock)
        p.feed(b"\xaa")
        clock.advance(100)
        for value in (1, [0xaa], "text", None):
            with self.assertRaises(TypeError):
                p.feed(value)
        self.assertEqual(p.pending, 1)
        self.assertEqual(p.timeouts, 0)

    def test_crc_failure_then_valid_frame(self):
        bad = bytearray(build_frame(b"\xaa\x55"))
        bad[-1] ^= 1
        p = FrameParser()
        self.assertEqual(p.feed(bad + build_frame(b"next")), [b"next"])
        self.assertEqual(p.crc_errors, 1)
        self.assertEqual(p.discarded, len(bad))

    def test_binary_payload_and_bytearray(self):
        payload = b"\x00\xaa\x55\xff"
        self.assertEqual(FrameParser().feed(bytearray(build_frame(bytearray(payload)))), [payload])
