"""串口帧编解码。

帧格式（小端）:

    +--------+--------+---------+-----------+
    | 0xAA   | 0x55   | LEN     | PAYLOAD   | CRC16 |
    +--------+--------+---------+-----------+
      2 byte   1 byte    N byte    2 byte

CRC 为 CRC-16/MODBUS，覆盖 LEN + PAYLOAD。
"""

from __future__ import annotations

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

    能处理三种真实串口里必然遇到的情况：
      * 粘包  —— 一次 read 拿到两帧
      * 半包  —— 一次 read 只拿到半帧
      * 错包  —— CRC 不对，丢弃并计数
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self.frames = 0
        self.crc_errors = 0
        self.discarded = 0

    def reset(self) -> None:
        self._buf.clear()
        self.frames = 0
        self.crc_errors = 0
        self.discarded = 0

    @property
    def pending(self) -> int:
        """缓冲区里还没成帧的字节数。"""
        return len(self._buf)

    def feed(self, data: bytes) -> list:
        self._buf.extend(data)
        out = []

        while True:
            start = self._buf.find(HEAD)

            if start < 0:
                # 完全没有帧头，只留最后一个字节（可能是 0xAA 的前半）
                if len(self._buf) > 1:
                    self.discarded += len(self._buf) - 1
                    del self._buf[:-1]
                break

            if start > 0:
                self.discarded += start
                del self._buf[:start]

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

            del self._buf[:total]

        return out

    def __repr__(self) -> str:
        return "<FrameParser frames=%d crc_errors=%d discarded=%d pending=%d>" % (
            self.frames, self.crc_errors, self.discarded, len(self._buf))
