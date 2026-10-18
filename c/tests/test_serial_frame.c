#include "serial_frame.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* CHECK stays active in Release builds (unlike assert with NDEBUG). */
#define CHECK(x) do { if (!(x)) { \
    fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #x); exit(1); \
} } while (0)

typedef struct {
    uint8_t payload[SF_MAX_PAYLOAD];
    size_t length;
    size_t calls;
} capture;

static void receive(const uint8_t *payload, size_t length, void *user)
{
    capture *result = user;
    memcpy(result->payload, payload, length);
    result->length = length;
    result->calls++;
}

static void test_roundtrips(void)
{
    uint8_t payload[SF_MAX_PAYLOAD];
    uint8_t frame[SF_MAX_FRAME];
    size_t length, split, i;
    for (i = 0; i < sizeof(payload); ++i) {
        payload[i] = (uint8_t)i;
    }
    /* Every length, every two-chunk boundary, including empty chunks. */
    for (length = 0; length <= SF_MAX_PAYLOAD; ++length) {
        size_t size = sf_build_frame(payload, length, frame, sizeof(frame));
        CHECK(size == length + SF_OVERHEAD);
        for (split = 0; split <= size; ++split) {
            sf_parser parser;
            capture result = {{0}, 0, 0};
            CHECK(sf_init(&parser, 50));
            (void)sf_feed(&parser, frame, split, 0, receive, &result);
            (void)sf_feed(&parser, frame + split, size - split, 1, receive, &result);
            CHECK(result.calls == 1 && result.length == length);
            CHECK(memcmp(result.payload, payload, length) == 0);
            CHECK(parser.frames == 1 && parser.pending == 0);
            CHECK(parser.crc_errors == 0 && parser.discarded == 0);
        }
    }
}

static void test_garbage_crc_and_sticky(void)
{
    sf_parser parser;
    uint8_t frame[SF_MAX_FRAME];
    const uint8_t payload[] = {0xaa, 0x55, 0, 0xff};
    const uint8_t noise[] = {0, 0xaa, 0xaa, 1, 0xaa};
    uint8_t stream[2 * SF_MAX_FRAME];
    size_t size = sf_build_frame(payload, sizeof(payload), frame, sizeof(frame));
    capture result = {{0}, 0, 0};
    CHECK(sf_init(&parser, 50));
    CHECK(sf_feed(&parser, noise, sizeof(noise), 0, NULL, NULL) == 0);
    CHECK(parser.pending == 1 && parser.discarded == 4);
    CHECK(sf_feed(&parser, frame, size, 1, receive, &result) == 1);
    CHECK(parser.discarded == sizeof(noise));
    CHECK(result.length == sizeof(payload));
    CHECK(memcmp(result.payload, payload, sizeof(payload)) == 0);
    memcpy(stream, frame, size);
    stream[size - 1] ^= 1u;
    memcpy(stream + size, frame, size);
    CHECK(sf_feed(&parser, stream, size * 2, 2, receive, &result) == 1);
    CHECK(parser.crc_errors == 1 && parser.discarded == sizeof(noise) + size);
    CHECK(parser.frames == 2 && result.calls == 2 && parser.pending == 0);
    CHECK(sf_feed(&parser, frame, size, 3, NULL, NULL) == 1);
    CHECK(parser.frames == 3);
}

static void test_timeout(void)
{
    sf_parser parser;
    uint8_t frame[SF_MAX_FRAME];
    size_t size = sf_build_frame((const uint8_t *)"abc", 3, frame, sizeof(frame));
    CHECK(sf_init(&parser, 50));
    (void)sf_feed(&parser, frame, 1, 0, NULL, NULL);
    (void)sf_feed(&parser, frame + 1, 1, 40, NULL, NULL);
    CHECK(sf_tick(&parser, 49) == 0);
    CHECK(sf_tick(&parser, 50) == 2);
    CHECK(sf_tick(&parser, 51) == 0 && parser.timeouts == 1);
    CHECK(parser.discarded == 2);
    (void)sf_feed(&parser, frame, 4, 60, NULL, NULL);
    CHECK(sf_feed(&parser, frame, size, 110, NULL, NULL) == 1);
    CHECK(parser.timeouts == 2 && parser.pending == 0);
    sf_reset(&parser);
    CHECK(parser.timeout_ms == 50 && parser.frames == 0 && parser.timeouts == 0);
    CHECK(parser.discarded == 0 && parser.crc_errors == 0);
    /* uint32 timer rollover: 0xfffffff0 -> 0x22 is exactly 50 ms. */
    (void)sf_feed(&parser, frame, 4, UINT32_MAX - 15u, NULL, NULL);
    CHECK(sf_tick(&parser, 33) == 0);
    CHECK(sf_tick(&parser, 34) == 4);
    CHECK(sf_init(&parser, 0));
    (void)sf_feed(&parser, frame, 4, 0, NULL, NULL);
    CHECK(sf_tick(&parser, 100000) == 0 && parser.pending == 4);
}

static void test_new_header_gets_new_deadline(void)
{
    sf_parser parser;
    uint8_t frame[SF_MAX_FRAME];
    uint8_t aa = 0xaa;
    const uint8_t noise[] = {0, 1};
    size_t size = sf_build_frame((const uint8_t *)"ok", 2, frame, sizeof(frame));
    CHECK(sf_init(&parser, 50));
    (void)sf_feed(&parser, &aa, 1, 0, NULL, NULL);
    (void)sf_feed(&parser, &aa, 1, 40, NULL, NULL);
    CHECK(sf_tick(&parser, 50) == 0);
    CHECK(sf_feed(&parser, frame + 1, size - 1, 60, NULL, NULL) == 1);
    (void)sf_feed(&parser, noise, sizeof(noise), 70, NULL, NULL);
    CHECK(parser.pending == 0 && sf_tick(&parser, 200) == 0);
    CHECK(parser.timeouts == 0 && parser.discarded == 3);
}

static void test_bad_arguments(void)
{
    sf_parser parser;
    uint8_t output[SF_MAX_FRAME];
    CHECK(!sf_init(NULL, 1));
    CHECK(!sf_init(&parser, UINT32_MAX));
    CHECK(sf_init(&parser, 50));
    CHECK(sf_build_frame(NULL, 0, output, sizeof(output)) == 5);
    CHECK(sf_build_frame(NULL, 1, output, sizeof(output)) == 0);
    CHECK(sf_build_frame(output, 256, output, sizeof(output)) == 0);
    CHECK(sf_build_frame(NULL, 0, output, 4) == 0);
    CHECK(sf_build_frame(NULL, 0, NULL, 5) == 0);
    (void)sf_feed(&parser, output, 2, 0, NULL, NULL);
    CHECK(sf_feed(&parser, NULL, 1, 100, NULL, NULL) == 0);
    CHECK(parser.pending == 2 && parser.timeouts == 0);
    CHECK(sf_feed(&parser, NULL, 0, 100, NULL, NULL) == 0);
    CHECK(parser.pending == 0 && parser.timeouts == 1);
    CHECK(sf_feed(NULL, NULL, 0, 0, NULL, NULL) == 0);
    CHECK(sf_tick(NULL, 0) == 0);
    sf_reset(NULL);
}

int main(void)
{
    CHECK(sf_crc16_modbus((const uint8_t *)"123456789", 9) == 0x4b37);
    CHECK(sf_crc16_modbus(NULL, 0) == 0xffff);
    test_roundtrips();
    test_garbage_crc_and_sticky();
    test_timeout();
    test_new_header_gets_new_deadline();
    test_bad_arguments();
    puts("C99 tests passed: all payload lengths and split points, CRC, timeout, rollover, API bounds");
    return 0;
}
