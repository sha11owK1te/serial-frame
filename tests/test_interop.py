"""Set SF_VECTOR_TOOL to the compiled sf_vector_tool path to enable C/Python checks."""
import os
import random
import subprocess
import unittest

from serial_frame import FrameParser, build_frame


@unittest.skipUnless(os.environ.get("SF_VECTOR_TOOL"), "C test bridge not configured")
class TestInterop(unittest.TestCase):
    def run_tool(self, mode, records):
        completed = subprocess.run(
            [os.environ["SF_VECTOR_TOOL"], mode],
            input="".join(record.hex() + "\n" for record in records),
            capture_output=True, text=True, check=True, timeout=30,
        )
        return [bytes.fromhex(line) for line in completed.stdout.splitlines()]

    def test_all_lengths_both_directions(self):
        rng = random.Random(2026)
        payloads = [bytes(rng.randrange(256) for _ in range(n)) for n in range(256)]
        c_frames = self.run_tool("build", payloads)
        self.assertEqual(c_frames, [build_frame(p) for p in payloads])
        self.assertEqual([FrameParser().feed(frame)[0] for frame in c_frames], payloads)
        self.assertEqual(self.run_tool("parse", list(map(build_frame, payloads))), payloads)

    def test_noisy_stream_and_crc_failure(self):
        bad = bytearray(build_frame(b"bad"))
        bad[-1] ^= 1
        payloads = [b"", b"\xaa\x55\x00\xff", bytes(range(255))]
        stream = b"\x00\xaa" + bytes(bad) + b"".join(map(build_frame, payloads))
        self.assertEqual(self.run_tool("parse", [stream]), FrameParser().feed(stream))
        self.assertEqual(self.run_tool("parse", [stream]), payloads)
