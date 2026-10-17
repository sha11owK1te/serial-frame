# serial-frame

零依赖的串口帧编解码器：构造帧、流式解析、CRC16 校验。

调试串口设备时，真正难的不是协议本身，而是**数据流会被任意切分**——
一次 `read()` 可能拿到半帧、两帧、或者半帧加一串垃圾字节。
这个库用流式状态机把「粘包 / 半包 / 错包」三种情况处理干净，只用 Python 标准库。

## 帧格式

```
+--------+--------+--------+-----------+--------+
| 0xAA   | 0x55   | LEN    | PAYLOAD   | CRC16  |
+--------+--------+--------+-----------+--------+
  2 byte           1 byte    N byte      2 byte
```

- `LEN` 为 payload 字节数，范围 0–255
- `CRC16` 为 CRC-16/MODBUS，覆盖 `LEN + PAYLOAD`，小端存放

## 用法

```python
from serial_frame import FrameParser, build_frame

frame = build_frame(b"hello")     # b'\xAA\x55\x05hello..'

parser = FrameParser()
parser.feed(frame[:3])            # 半包 -> []
parser.feed(frame[3:])            # 补齐 -> [b'hello']
```

## 命令行

```bash
# 打包
python -m serial_frame.cli build "temp=25.3"

# 解析一段十六进制数据流
python -m serial_frame.cli parse "AA 55 05 68 65 6C 6C 6F 76 A5"

# 演示：随机切片喂进去，看它怎么把碎片拼回来
python -m serial_frame.cli demo
```

`demo` 会打印每一块碎片和对应的解析结果，用来观察粘包与半包的处理过程。

## 测试

```bash
python -m unittest discover -s tests -t . -v
```

覆盖：CRC 标准值、空 payload、超长 payload、单帧、粘包、逐字节喂入、
CRC 错误、垃圾前缀、半包后补齐。

## 设计取舍

- **不依赖 `pyserial`**：只做编解码，收发交给调用方，方便在任何环境测试。
- **解析器有状态**：不要求一次喂完整帧，这是它能处理半包的前提。
- **CRC 不匹配时整帧丢弃**：不尝试重同步到帧内，因为 payload 里可能出现任意字节。

## License

MIT
