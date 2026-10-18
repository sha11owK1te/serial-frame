/* Host-only test bridge: one hex record per line, build or parse mode. */
#include "serial_frame.h"
#include <stdio.h>
#include <string.h>

static void print_hex(const uint8_t *data, size_t length, void *user)
{
    size_t i;
    (void)user;
    for (i = 0; i < length; ++i) {
        printf("%02x", (unsigned)data[i]);
    }
    putchar('\n');
}

static int nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

int main(int argc, char **argv)
{
    char line[4096];
    if (argc != 2 || (strcmp(argv[1], "build") != 0 && strcmp(argv[1], "parse") != 0)) {
        return 2;
    }
    while (fgets(line, sizeof(line), stdin) != NULL) {
        uint8_t bytes[2048];
        size_t length = strcspn(line, "\r\n");
        size_t i;
        if (length % 2 != 0 || length / 2 > sizeof(bytes)) return 2;
        for (i = 0; i < length / 2; ++i) {
            int high = nibble(line[i * 2]);
            int low = nibble(line[i * 2 + 1]);
            if (high < 0 || low < 0) return 2;
            bytes[i] = (uint8_t)(high * 16 + low);
        }
        length /= 2;
        if (strcmp(argv[1], "build") == 0) {
            uint8_t frame[SF_MAX_FRAME];
            size_t size = sf_build_frame(bytes, length, frame, sizeof(frame));
            if (size == 0) return 2;
            print_hex(frame, size, NULL);
        } else {
            sf_parser parser;
            (void)sf_init(&parser, 0);
            for (i = 0; i < length; ++i) {
                (void)sf_feed(&parser, bytes + i, 1, 0, print_hex, NULL);
            }
        }
    }
    return ferror(stdin) || ferror(stdout) ? 1 : 0;
}
