# 本次本地验证记录

日期：2026-10-17。基于原仓库提交 `7bc7270` 进行修改。

## 已执行

环境：Windows x64、Python 3.13.9、TinyCC 0.9.27。
编译器位于开发工作目录，不是项目运行依赖，不包含在源码交付包中。

```text
tcc -std=c99 -Wall -Werror -Ic/include c/src/serial_frame.c c/tests/test_serial_frame.c -o build/test_serial_frame.exe
build/test_serial_frame.exe

tcc -std=c99 -Wall -Werror -Ic/include c/src/serial_frame.c c/tests/vector_tool.c -o build/sf_vector_tool.exe
SF_VECTOR_TOOL=<absolute path to sf_vector_tool.exe>
python -m unittest discover -s tests -t . -v
```

结果：C 核心测试通过；Python 36 项测试通过，包含 2 项跨语言互操作测试，无跳过项。
C 与 Python 分别测试所有 256 种 payload 长度的全部两段拆包位置，
每套实现共 34,176 种长度/拆包组合。
另含标准 CRC 校验值、随机二进制与分块、CRC 错误、超时和 C 计时器回绕检查。

## 尚未验证

- 本机未安装 CMake，实际通过上述直接编译命令验证；CMake 构建路径待 CI 执行。
- GitHub Actions 中新增的 GCC/Clang、AddressSanitizer/UBSan 配置尚未运行。
- 未在开发板上编译、烧录或测量 UART/DMA/RTOS、栈开销、资源占用和吞吐率。

主机验证不能替代具体 MCU 的编译、驱动适配和硬件测试。
