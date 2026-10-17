"""命令行入口：python -m serial_frame.cli <command>"""

from __future__ import annotations

import argparse
import random
import sys

from .codec import FrameParser, build_frame


def _hex(data: bytes) -> str:
    return " ".join("%02X" % b for b in data)


def cmd_build(args) -> int:
    payload = args.payload.encode("utf-8")
    frame = build_frame(payload)
    print("payload : %r  (%d bytes)" % (args.payload, len(payload)))
    print("frame   : %s" % _hex(frame))
    return 0


def cmd_parse(args) -> int:
    raw = bytes.fromhex(args.data.replace(" ", ""))
    parser = FrameParser()
    for payload in parser.feed(raw):
        print("payload : %-24s %r" % (_hex(payload), payload.decode("utf-8", "replace")))
    print("stats   : frames=%d crc_errors=%d discarded=%d pending=%d"
          % (parser.frames, parser.crc_errors, parser.discarded, parser.pending))
    return 0


def cmd_demo(args) -> int:
    """构造三帧，随机切片喂进去，看解析器怎么把碎片拼回来。"""
    random.seed(args.seed)

    payloads = [b"temp=25.3", b"humi=61", b"adc=4095"]
    stream = b"".join(build_frame(p) for p in payloads)
    stream = b"\x00\x13\x37" + stream  # 前面掺三个垃圾字节

    print("原始数据流 (%d bytes):" % len(stream))
    print("  " + _hex(stream))
    print()

    parser = FrameParser()
    cursor = 0
    step = 0
    while cursor < len(stream):
        size = random.randint(1, 6)
        chunk = stream[cursor:cursor + size]
        got = parser.feed(chunk)
        step += 1
        print("[chunk %02d] 收到 %-18s -> 解析出 %d 帧" % (step, _hex(chunk), len(got)))
        for p in got:
            print("            %r" % p)
        cursor += size

    print()
    print("结果: frames=%d crc_errors=%d discarded=%d pending=%d"
          % (parser.frames, parser.crc_errors, parser.discarded, parser.pending))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="serial_frame.cli", description="串口帧解析器")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="把文本打包成一帧")
    p_build.add_argument("payload")
    p_build.set_defaults(func=cmd_build)

    p_parse = sub.add_parser("parse", help="解析十六进制数据流")
    p_parse.add_argument("data")
    p_parse.set_defaults(func=cmd_parse)

    p_demo = sub.add_parser("demo", help="演示粘包 / 半包 / 垃圾数据")
    p_demo.add_argument("--seed", type=int, default=7)
    p_demo.set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
