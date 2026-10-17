import unittest

from serial_frame.codec import FrameParser, build_frame, crc16_modbus


class FakeClock:
    """可拨动的假时钟，让超时测试不依赖 sleep。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += ms / 1000.0


class TestCRC(unittest.TestCase):
    def test_known_value(self):
        # CRC-16/MODBUS 的标准校验值
        self.assertEqual(crc16_modbus(b"123456789"), 0x4B37)

    def test_empty(self):
        self.assertEqual(crc16_modbus(b""), 0xFFFF)


class TestBuild(unittest.TestCase):
    def test_header_and_length(self):
        frame = build_frame(b"hello")
        self.assertEqual(frame[0:2], b"\xAA\x55")
        self.assertEqual(frame[2], 5)
        self.assertEqual(len(frame), 5 + 5)

    def test_empty_payload(self):
        frame = build_frame(b"")
        self.assertEqual(len(frame), 5)
        self.assertEqual(frame[2], 0)

    def test_too_long(self):
        with self.assertRaises(ValueError):
            build_frame(b"x" * 256)


class TestParser(unittest.TestCase):
    def test_single_frame(self):
        p = FrameParser()
        self.assertEqual(p.feed(build_frame(b"abc")), [b"abc"])

    def test_sticky(self):
        p = FrameParser()
        data = build_frame(b"a") + build_frame(b"b") + build_frame(b"c")
        self.assertEqual(p.feed(data), [b"a", b"b", b"c"])
        self.assertEqual(p.frames, 3)

    def test_byte_by_byte(self):
        p = FrameParser()
        data = build_frame(b"hello world")
        out = []
        for i in range(len(data)):
            out += p.feed(data[i:i + 1])
        self.assertEqual(out, [b"hello world"])
        self.assertEqual(p.pending, 0)

    def test_crc_error(self):
        p = FrameParser()
        bad = bytearray(build_frame(b"abc"))
        bad[-1] ^= 0xFF
        self.assertEqual(p.feed(bytes(bad)), [])
        self.assertEqual(p.crc_errors, 1)

    def test_garbage_prefix(self):
        p = FrameParser()
        data = b"\x01\x02\x03" + build_frame(b"ok")
        self.assertEqual(p.feed(data), [b"ok"])
        self.assertEqual(p.discarded, 3)

    def test_pending_after_half(self):
        p = FrameParser()
        frame = build_frame(b"abcdef")
        self.assertEqual(p.feed(frame[:4]), [])
        self.assertGreater(p.pending, 0)
        self.assertEqual(p.feed(frame[4:]), [b"abcdef"])


class TestHalfFrameTimeout(unittest.TestCase):
    """半帧超时：残字节不会永远占住缓冲区。"""

    TIMEOUT = 50  # ms

    def _parser(self):
        clock = FakeClock()
        return FrameParser(timeout_ms=self.TIMEOUT, clock=clock), clock

    def test_disabled_by_default(self):
        p = FrameParser()
        p.feed(build_frame(b"abc")[:4])
        p.tick()
        self.assertGreater(p.pending, 0)
        self.assertEqual(p.timeouts, 0)

    def test_kept_before_deadline(self):
        p, clock = self._parser()
        p.feed(build_frame(b"abc")[:4])
        clock.advance(self.TIMEOUT - 10)
        self.assertEqual(p.tick(), 0)
        self.assertEqual(p.timeouts, 0)

    def test_expires_after_deadline(self):
        p, clock = self._parser()
        p.feed(build_frame(b"abc")[:4])
        clock.advance(self.TIMEOUT + 10)
        self.assertEqual(p.tick(), 4)
        self.assertEqual(p.pending, 0)
        self.assertEqual(p.timeouts, 1)

    def test_discarded_bytes_counted(self):
        p, clock = self._parser()
        p.feed(build_frame(b"abcdef")[:5])
        clock.advance(self.TIMEOUT + 10)
        p.tick()
        self.assertEqual(p.discarded, 5)

    def test_expired_buffer_never_yields_a_frame(self):
        p, clock = self._parser()
        frame = build_frame(b"hello")
        p.feed(frame[:4])
        clock.advance(self.TIMEOUT + 10)
        # 剩下的半帧补上来，但前面的字节已经被丢掉，拼不出完整帧
        self.assertEqual(p.feed(frame[4:]), [])
        self.assertEqual(p.frames, 0)
        self.assertEqual(p.timeouts, 1)

    def test_feed_triggers_expiry_too(self):
        p, clock = self._parser()
        p.feed(build_frame(b"abc")[:4])
        clock.advance(self.TIMEOUT + 10)
        # 新到的一整帧不应被旧残字节连累，照常解析出来
        self.assertEqual(p.feed(build_frame(b"ok")), [b"ok"])
        self.assertEqual(p.timeouts, 1)
        self.assertEqual(p.frames, 1)

    def test_stamp_not_refreshed_by_drip(self):
        """一字节一字节慢慢挤，也不能把计时器一直往后推。"""
        p, clock = self._parser()
        frame = build_frame(b"abcdef")
        p.feed(frame[0:1])       # t=0     , 残字节 1 个
        clock.advance(40)
        p.feed(frame[1:2])       # t=40ms  , 仍在前一字节的计时窗口里
        clock.advance(20)
        # t=60ms 已超过 50ms，说明第二个字节没有把计时器刷新到 t=40
        self.assertEqual(p.tick(), 2)
        self.assertEqual(p.timeouts, 1)

    def test_slow_but_within_timeout_still_parses(self):
        p, clock = self._parser()
        frame = build_frame(b"abcd")
        out = []
        for i in range(len(frame)):
            out += p.feed(frame[i:i + 1])
            clock.advance(5)
        self.assertEqual(out, [b"abcd"])
        self.assertEqual(p.timeouts, 0)

    def test_complete_frame_leaves_no_stamp(self):
        p, clock = self._parser()
        self.assertEqual(p.feed(build_frame(b"abc")), [b"abc"])
        clock.advance(self.TIMEOUT * 10)
        self.assertEqual(p.tick(), 0)
        self.assertEqual(p.timeouts, 0)

    def test_stamp_resets_after_each_frame(self):
        p, clock = self._parser()
        p.feed(build_frame(b"a") + build_frame(b"b"))
        p.feed(build_frame(b"c")[:3])
        clock.advance(self.TIMEOUT - 10)
        self.assertEqual(p.tick(), 0)
        clock.advance(20)
        self.assertEqual(p.tick(), 3)

    def test_counter_accumulates(self):
        p, clock = self._parser()
        for _ in range(3):
            p.feed(build_frame(b"xyz")[:4])
            clock.advance(self.TIMEOUT + 1)
            p.tick()
        self.assertEqual(p.timeouts, 3)

    def test_recovery_after_timeout(self):
        p, clock = self._parser()
        p.feed(build_frame(b"dead")[:4])
        clock.advance(self.TIMEOUT + 1)
        p.tick()
        self.assertEqual(p.feed(build_frame(b"live")), [b"live"])
        self.assertEqual(p.frames, 1)

    def test_reset_clears_timeout_state(self):
        p, clock = self._parser()
        p.feed(build_frame(b"abc")[:4])
        clock.advance(self.TIMEOUT + 1)
        p.tick()
        p.reset()
        self.assertEqual(p.timeouts, 0)
        self.assertEqual(p.discarded, 0)
        clock.advance(self.TIMEOUT * 2)
        self.assertEqual(p.tick(), 0)

    def test_invalid_timeout_rejected(self):
        for bad in (0, -1, -0.5):
            with self.assertRaises(ValueError):
                FrameParser(timeout_ms=bad)

    def test_repr_exposes_timeouts(self):
        p = FrameParser(timeout_ms=10)
        self.assertIn("timeouts=0", repr(p))


if __name__ == "__main__":
    unittest.main()
