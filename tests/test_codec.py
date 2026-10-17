import unittest

from serial_frame.codec import FrameParser, build_frame, crc16_modbus


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


if __name__ == "__main__":
    unittest.main()
