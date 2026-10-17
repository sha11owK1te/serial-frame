# serial-frame

![CI](https://github.com/sha11owK1te/serial-frame/actions/workflows/ci.yml/badge.svg)

零依赖的串口帧编解码器：构造帧、流式解析、CRC16 校验、半帧超时回收。

调试串口设备时，真正难的不是协议本身，而是**数据流会被任意切分**——
一次 `read()` 可能拿到半帧、两帧、或者半帧加一串垃圾字节。
这个库用流式状态机把「粘包 / 半包 / 错包 / 死包」四种情况处理干净，只用 Python 标准库。

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

带半帧超时：

```python
parser = FrameParser(timeout_ms=200)

while running:
    chunk = ser.read(ser.in_waiting or 1)   # 读不到也要转一圈
    for payload in parser.feed(chunk):
        handle(payload)
    parser.tick()                           # 半帧等太久就丢掉
```

`feed()` 会返回本次拼出的 payload 列表；`tick()` 返回本次因超时丢弃的字节数。
两者都幂等，多调几次不会重复计数。

## 命令行

```bash
# 打包
python -m serial_frame.cli build "temp=25.3"

# 解析一段十六进制数据流
python -m serial_frame.cli parse "AA 55 05 68 65 6C 6C 6F 76 A5"

# 演示：随机切片喂进去，看它怎么把碎片拼回来；末尾再演一次半帧超时
python -m serial_frame.cli demo
python -m serial_frame.cli demo --timeout-ms 0     # 关掉超时那一幕
```

`demo` 第一幕打印每一块碎片和对应的解析结果，用来观察粘包与半包的处理过程；
第二幕喂半帧进去、等过阈值、调 `tick()`，把丢弃的字节数和计数打出来。

## 测试

```bash
python -m unittest discover -s tests -t . -v
```

26 个测试，覆盖：CRC 标准值、空 payload、超长 payload、单帧、粘包、逐字节喂入、
CRC 错误、垃圾前缀、半包后补齐，以及超时的 15 种情形——
到期与未到期、`tick()` 与 `feed()` 两种触发路径、计时起点不被新字节刷新、
超时后仍能正常解析后续帧、计数累加、`reset()` 清零、非法参数拒绝。

超时测试用**注入的假时钟**（`FrameParser(timeout_ms=50, clock=fake)`），
不靠 `sleep`。整套测试跑完 0.001s，也不会因为 CI 机器卡顿而偶发失败。

## 我加了什么、为什么加

模板版本只会「等下一块数据到齐」。这在真机上有个要命的失效模式。

### 问题：半帧会永久堵死解析器

假设对端发了一帧，`LEN=0x09`，结果只发出 4 个字节就断线了。这 4 个字节停在缓冲区
首位，`feed()` 每次进来发现「还差 5 字节」，就 `break` 等下一轮。之后对端恢复，发来
一整帧合法数据——解析器仍然认为前面那半帧没结束，新帧被当成它的尾巴一起吃掉，
CRC 校验失败，整段丢弃，然后继续等。**解析器一直在工作，但再也吐不出任何一帧。**

这种半帧在串口上不是理论情况：MCU 复位、RS-485 收发器切换时拉低总线、LEN 字节被
干扰打乱导致长度算错，都能造出来。模板没有兜底，等于把「链路抖动一次」放大成
「进程重启才能恢复」。

### 做法

- `FrameParser(timeout_ms=...)`，默认 `None` 保持原行为，原有 11 个测试一行没改。
- 新增内部状态 `_waiting_since`：记录残字节**第一次**出现的时刻。
- 新增计数器 `timeouts`；超时丢弃的字节同时计入已有的 `discarded`。
- 新增 `tick()` 供调用方轮询，`feed()` 入口也会检查一次。
- 时钟可注入：默认 `time.monotonic`，测试传假时钟。

### 三个想清楚才写对的点

**1. 谁来发现「没有数据」？**
状态机的所有逻辑都挂在 `feed()` 上，而对端不发数据时 `feed()` 根本不会被调用——
超时检查永远不会发生。这不是能靠内部再憋一个线程绕过去的（嵌入式场景里也不该那么做），
只能由调用方在自己的读循环里每轮 `tick()` 一次。所以这条约束写进了 docstring 和上面的
用法示例里，而不是让 `timeout_ms` 变成一个静默失效的开关。

**2. 计时起点不能刷新。**
第一版写成每次 `feed()` 都把 `_waiting_since` 更新成当前时间，结果一字节一字节慢慢挤的
设备永远超时不了：每来一个新字节就给残帧续命一次。改成只在缓冲区从空变非空时打点，
`test_stamp_not_refreshed_by_drip` 就是钉这个行为的。

**3. 超时后整段丢弃，不尝试重新同步。**
和 CRC 失败时的处理保持一致：payload 里可能出现任意字节，在缓冲区内部扫 `0xAA 0x55`
只会把真正的数据当成帧头，制造更多误判。宁可丢掉这半帧，让下一帧从干净的缓冲区开始。
边界也划清了：只有「缓冲区里已有残字节」才可能超时，空缓冲区不产生超时，否则每轮
`tick()` 都会凭空 +1。

## 设计取舍

- **不依赖 `pyserial`**：只做编解码，收发交给调用方，方便在任何环境测试。
- **解析器有状态**：不要求一次喂完整帧，这是它能处理半包的前提。
- **CRC 不匹配时整帧丢弃**：不尝试重同步到帧内，因为 payload 里可能出现任意字节。
- **超时需要调用方配合轮询**：库不自己起线程、不读时钟之外的资源，保持单线程可预测。

## License

MIT
