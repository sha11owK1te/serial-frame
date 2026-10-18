# serial-frame

![CI](https://github.com/sha11owK1te/serial-frame/actions/workflows/ci.yml/badge.svg)

面向 UART 字节流的帧编解码器：**C99 MCU 核心 + Python 上位机参考实现**。
支持任意拆包、连续多帧、CRC16 校验和可选的半帧超时。

C 核心不依赖 HAL、RTOS 或动态内存；Python 运行时只使用标准库。
当前提供主机自动化验证，**尚未完成开发板 UART/DMA 实测**。

## 协议

```text
AA 55 | LEN (1 byte) | PAYLOAD (0..255 bytes) | CRC16 (2 bytes, little-endian)
```

CRC-16/MODBUS：多项式反射值 `0xA001`，初值 `0xFFFF`，xorout `0x0000`，
覆盖 `LEN + PAYLOAD`。标准校验向量 `123456789 → 0x4B37`。
最大帧长 260 字节，payload 可包含任意二进制字节，包括 `AA 55`。

## C99 快速开始

将 `c/src/serial_frame.c` 和 `c/include/serial_frame.h` 加入 MCU 工程即可。

```c
#include "serial_frame.h"

static sf_parser parser; /* 持久保存，不能每次收数据都初始化 */

static void on_frame(const uint8_t *payload, size_t length, void *user)
{
    /* 在回调内处理或复制 payload；回调返回后指针内容可能被覆盖。 */
    (void)payload;
    (void)length;
    (void)user;
}

void app_init(void)
{
    (void)sf_init(&parser, 100); /* ms，0 关闭超时 */
}

void app_receive(const uint8_t *data, size_t length, uint32_t now_ms)
{
    (void)sf_feed(&parser, data, length, now_ms, on_frame, NULL);
}

void app_poll(uint32_t now_ms)
{
    (void)sf_tick(&parser, now_ms); /* 没收到数据也应定期调用 */
}
```

`sf_build_frame()` 将 payload 编码到调用方提供的缓冲区，返回帧长；
容量不足或参数非法返回 0。`sf_feed()` 返回本次有效帧数。
完整 API 约束见 [头文件](c/include/serial_frame.h)。

### 主机构建与测试

需要 C99 编译器及 CMake 3.16+：

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
ctest --test-dir build --output-on-failure
```

核心持有一个 260 字节帧缓冲区，以及长度、时钟和统计状态；
实际结构体大小取决于 ABI。逐字节接收，不随传入数据块长度增加内部缓冲容量。
返回 payload 的回调由调用方负责处理，核心不创建线程、不负责串口收发。

## Python 上位机参考

在仓库根目录运行：

```python
from serial_frame import FrameParser, build_frame

frame = build_frame(b"hello")
parser = FrameParser(timeout_ms=100)
assert parser.feed(frame[:3]) == []
assert parser.feed(frame[3:]) == [b"hello"]
parser.tick()  # 接入读循环后，即使没有新数据也要周期调用
```

```bash
python -m serial_frame.cli build "temp=25.3"
python -m serial_frame.cli parse "AA 55 05 68 65 6C 6C 6F D2 7A"
python -m serial_frame.cli demo
python -m unittest discover -s tests -t . -v
```

串口适配器应使用有限的读取等待时间，确保 `tick()` 能得到执行。
Python 中 `timeout_ms=None` 关闭超时，启用时必须为有限正数。

## 超时、错误与恢复边界

- 每个候选帧从首个 `AA` 开始计时，后续字节不延长截止时间。
  如果头部被噪声打断后重新出现 `AA`，新候选帧获得新的计时窗口。
- 超时在 `feed()` 入口或 `tick()` 中检查，`tick()` 返回丢弃字节数。
  截止时刻及之后到达的尾部会按超时处理。
- CRC 错误丢弃当前长度字段指定的整个候选帧，不回扫其内部帧头。
- 超时丢弃当前残帧。普通垃圾立即计入 `discarded`，仅保留可能跨块的 `AA`。
- `frames` 为成功帧数；`crc_errors` 为完整候选帧 CRC 失败数；
  `discarded` 包括噪声、CRC 失败帧和超时字节；`timeouts` 为超时事件数。
- `reset()` 清空缓冲和统计；保留超时配置。解析器需要串行调用。

**恢复能力有边界**：长度字段损坏时，后续合法帧可能被当作当前帧内容并一同丢弃。
超时也无法找回已经丢弃的帧。本协议不提供确认、重传、序列号或可靠交付保证；
CRC 用于误码检测，不保证检测所有错误。需要可靠交付时，应在上层设计相应机制。

## 验证内容

- 原有 Python 测试保留，新增噪声、候选帧重新计时、参数与统计回归测试。
- C/Python 各自覆盖 0–255 所有 payload 长度及每个两段拆包位置。
- 固定种子的随机二进制 payload、随机分块及字节统计守恒检查。
- C 测试覆盖空帧、最大帧、CRC 错帧后续帧、超时边界、滴流不续期、
  `uint32_t` 毫秒时钟回绕、输出容量不足和非法指针组合。
- C/Python 互操作测试比较所有长度的编码结果，并将 Python 帧逐字节交给 C 解码。
- CI 配置 Python 3.9–3.13，以及 GCC/Clang 的 C 测试和 AddressSanitizer/UBSan。
  新增工作流是否通过，应以 GitHub Actions 实际运行结果为准。

Linux/macOS 上启用互操作测试：

```bash
SF_VECTOR_TOOL=./build/sf_vector_tool python -m unittest discover -s tests -t . -v
```

Windows PowerShell（多配置 CMake 生成器可能位于 `build/Debug/`）：

```powershell
$env:SF_VECTOR_TOOL = (Resolve-Path ./build/sf_vector_tool.exe).Path
python -m unittest discover -s tests -t . -v
```

未设置 `SF_VECTOR_TOOL` 时仅跳过两项互操作测试，其他 Python 测试照常执行。

## MCU 接入与项目展示

- [移植说明及硬件验收步骤](docs/embedded-porting.md)
- [项目经历表述与面试准备](docs/resume-and-interview.md)

推荐下一步选择手头开发板，接入 UART 中断或 DMA 接收，并保存故障注入日志。
这能为项目增加板端实现和测量证据。

## License

MIT
