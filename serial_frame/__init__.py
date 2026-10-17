"""serial-frame: 零依赖的串口帧编解码器。"""

from .codec import FrameParser, build_frame, crc16_modbus

__all__ = ["FrameParser", "build_frame", "crc16_modbus"]
__version__ = "0.1.0"
