"""串口帧编解码。

帧格式（小端）:

    +--------+--------+---------+-----------+
    | 0xAA   | 0x55   | LEN     | PAYLOAD   | CRC16 |
    +--------+--------+---------+-----------+
      2 byte   1 byte    N byte    2 byte

CRC 为 CRC-16/MODBUS，覆盖 LEN + PAYLOAD。

解析器支持半帧超时：帧收到一半对端就不再发（掉电、断线、或者 LEN 被干扰打乱），
残字节会永久占住缓冲区，后面的正常帧全部被它挡住。设置 timeout_ms 后，
半帧等待超过该时长即被丢弃并计入 timeouts。
"""

from __future__ import annotations

import time
import math

HEAD = b"\xAA\x55"
MAX_PAYLOAD = 255
OVERHEAD = 5  # head(2) + len(1) + crc(2)


def crc16_modbus(data: bytes) -> int:
    """CRC-16/MODBUS: poly=0x8005 (reflected 0xA001), init=0xFFFF, xorout=0x0000."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_frame(payload: bytes) -> bytes:
    """把一段 payload 打包成完整帧。"""
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload too long: %d > %d" % (len(payload), MAX_PAYLOAD))

    body = bytes([len(payload)]) + bytes(payload)
    crc = crc16_modbus(body)
    return HEAD + body + crc.to_bytes(2, "little")


class FrameParser:
    """流式解析器。

    feed() 接受任意切分的字节块，返回这一轮拼出来的完整 payload 列表。
    没拼完的数据留在内部缓冲区，下次继续。

    能处理四种真实串口里必然遇到的情况：
      * 粘包  —— 一次 read 拿到两帧
      * 半包  —— 一次 read 只拿到半帧
      * 错包  —— CRC 不对，丢弃并计数
      * 死包  —— 半帧等到超时，丢弃并计数（需显式给 timeout_ms）

    超时机制需要注意的语义：
      状态机看不到「没有事件」这件事。半帧之后对端不再发数据，feed()
      就再也不会被调用，超时检查也就永远不会发生。所以调用方必须在
      自己的读循环里定期调用 tick()——哪怕这一轮读到零字节——
      否则 timeout_ms 只是个装饰品。
    """

    def __init__(self, timeout_ms: float = None, clock=None) -> None:
        if timeout_ms is not None:
            self.timeout_ms = float(timeout_ms)
            if not math.isfinite(self.timeout_ms) or self.timeout_ms <= 0:
                raise ValueError("timeout_ms must be finite and positive")
        else:
            self.timeout_ms = None

        # 时钟可注入：单元测试不靠 sleep，直接拨表针。
        self._clock = clock or time.monotonic

        self._buf = bytearray()
        self._waiting_since = None

        self.frames = 0
        self.crc_errors = 0
        self.discarded = 0
        self.timeouts = 0

    def reset(self) -> None:
        self._buf.clear()
        self._waiting_since = None
        self.frames = 0
        self.crc_errors = 0
        self.discarded = 0
        self.timeouts = 0

    @property
    def pending(self) -> int:
        """缓冲区里还没成帧的字节数。"""
        return len(self._buf)

    def tick(self) -> int:
        """主动检查半帧是否超时，返回本次丢弃的字节数。

        读循环里应当每轮都调一次，包括读到 0 字节的那一轮。
        """
        return self._expire_if_stale()

    def _expire_if_stale(self) -> int:
        if self.timeout_ms is None or self._waiting_since is None or not self._buf:
            return 0

        if self._clock() - self._waiting_since < self.timeout_ms / 1000.0:
            return 0

        dropped = len(self._buf)
        self._buf.clear()
        self._waiting_since = None
        self.discarded += dropped
        self.timeouts += 1
        return dropped

    def feed(self, data: bytes) -> list:
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("data must be bytes or bytearray")
        self._expire_if_stale()
        self._buf.extend(data)
        out = []

        while True:
            start = self._buf.find(HEAD)

            if start < 0:
                # 只有 0xAA 才可能是跨块帧头；普通垃圾不能产生半帧超时。
                keep = 1 if self._buf.endswith(HEAD[:1]) else 0
                dropped = len(self._buf) - keep
                if dropped:
                    self.discarded += dropped
                    del self._buf[:dropped]
                    self._waiting_since = None
                break

            if start > 0:
                self.discarded += start
                del self._buf[:start]
                self._waiting_since = None

            if len(self._buf) < 3:
                break  # 连长度字节都没收到

            length = self._buf[2]
            total = OVERHEAD + length
            if len(self._buf) < total:
                break  # 半包，等下一块

            body = bytes(self._buf[2:3 + length])
            crc_rx = int.from_bytes(self._buf[3 + length:total], "little")

            if crc16_modbus(body) == crc_rx:
                out.append(bytes(self._buf[3:3 + length]))
                self.frames += 1
            else:
                self.crc_errors += 1
                self.discarded += total

            del self._buf[:total]
            self._waiting_since = None  # 一帧结束，剩余字节属于新的一帧

        if self._buf:
            # 只记录「这批残字节第一次出现」的时刻，之后不再刷新，
            # 否则每次喂一个字节都会把计时器推后，超时永远不触发。
            if self._waiting_since is None:
                self._waiting_since = self._clock()
        else:
            self._waiting_since = None

        return out

    def __repr__(self) -> str:
        return "<FrameParser frames=%d crc_errors=%d discarded=%d timeouts=%d pending=%d>" % (
            self.frames, self.crc_errors, self.discarded, self.timeouts, len(self._buf))

