#include "config_validate.h"
#include "http_parse.h"
#include "outbox.h"
#include "protocol.h"
#include "render.h"
#include "usb_line.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;

int verify_outbox_packets(void);
int verify_upload_packets(void);

static void expect(int cond, const char *msg) {
  if (!cond) {
    fprintf(stderr, "FAIL %s\n", msg);
    failures++;
  }
}

static int hex_byte(char c) {
  if (c >= '0' && c <= '9') {
    return c - '0';
  }
  if (c >= 'a' && c <= 'f') {
    return c - 'a' + 10;
  }
  if (c >= 'A' && c <= 'F') {
    return c - 'A' + 10;
  }
  return -1;
}

static size_t unhex(const char *hex, uint8_t *out, size_t max) {
  size_t n = 0;
  while (hex[0] && hex[1] && n < max) {
    int hi = hex_byte(hex[0]);
    int lo = hex_byte(hex[1]);
    if (hi < 0 || lo < 0) {
      break;
    }
    out[n++] = (uint8_t)((hi << 4) | lo);
    hex += 2;
  }
  return n;
}

static void test_bluetooth_uuid(void) {
  uint8_t uuid[16];
  unhex("fb349b5f8000008000100000b0ff0000", uuid, sizeof(uuid));
  expect(bluetooth_uuid128_to_u16(uuid) == 0xFFB0, "captured 128-bit FFB0 service");

  /* Matching the low 16 bits alone aliases vendor bases and wider identifiers. */
  for (size_t i = 0; i < sizeof(uuid); i++) {
    if (i == 12 || i == 13) {
      continue;
    }
    uuid[i] ^= 1;
    expect(bluetooth_uuid128_to_u16(uuid) == 0, "do not alias unrelated UUIDs");
    uuid[i] ^= 1;
  }
}

static void test_reassembly(void) {
  static const char *f0 =
      "00001e00aab37116206425010a2500000000003d";
  static const char *f1 =
      "00001e0100000000000000000000000000000020";
  uint8_t a[64], b[64];
  size_t  la = unhex(f0, a, sizeof(a));
  size_t  lb = unhex(f1, b, sizeof(b));
  frame_assembler_t as;
  packet_t          pkt;
  decoded_t         dec;
  capabilities_t    caps;
  uint8_t           ack[FRAME_MAX];
  int               ack_len;

  frame_assembler_init(&as);
  expect(frame_assembler_add(&as, b, lb, &pkt) == 0, "ooo tail");
  expect(frame_assembler_add(&as, b, lb, &pkt) == 0, "retransmit tail");
  expect(frame_assembler_add(&as, a, la, &pkt) == 1, "complete info");
  expect(pkt.length == 30, "info length");
  expect(decode_packet(&pkt, NULL, &dec) == 0, "decode info");
  expect(dec.type == PKT_DEVICE_INFO, "type info");
  expect(decode_capabilities(pkt.payload, pkt.length, &caps) == 0, "caps");
  expect(caps.electrodes == 8, "electrodes");
  expect(caps.frequency_count == 2, "freq");
  expect(caps.impedances_per_frequency == 5, "ipf");
  ack_len = acknowledge(&pkt, 0, ack);
  expect(ack_len == 8, "ack len");
  expect(ack[4] == 0xB0 && ack[5] == 0 && ack[6] == 0, "ack payload");
}

static void test_padded_a7(void) {
  uint8_t payload[64];
  size_t  plen = unhex(
      "a712345678250124f8000a03e807d00bb80fa0138817701b581f4023282710ffffffff000000",
      payload, sizeof(payload));
  uint8_t frames[8][FRAME_MAX];
  int     lens[8];
  int     n = encode_frames(payload, plen, 1, 1, 20, frames, lens, 8);
  uint8_t padded[FRAME_MAX];
  int     i;
  frame_assembler_t as;
  packet_t          pkt;
  decoded_t         dec;
  capabilities_t    caps;
  uint8_t           info[32];
  size_t            ilen;
  int               got = 0;

  expect(n >= 2, "a7 frames");
  {
    int      cap      = 20 - 5;
    int      last_len = lens[n - 1];
    int      chunk    = last_len - 5;
    uint8_t  sum      = 0;
    uint8_t  unit     = frames[n - 1][last_len - 1] >> 5;

    memcpy(padded, frames[n - 1], (size_t)last_len);
    for (i = chunk; i < cap; i++) {
      padded[4 + i] = (uint8_t)(0xA0 + (i - chunk));
    }
    for (i = 0; i < cap; i++) {
      sum = (uint8_t)(sum + padded[4 + i]);
    }
    padded[4 + cap] = (uint8_t)((unit << 5) | (sum & 31));
    memcpy(frames[n - 1], padded, (size_t)(5 + cap));
    lens[n - 1] = 5 + cap;
  }
  frame_assembler_init(&as);
  for (i = 0; i < n; i++) {
    int r = frame_assembler_add(&as, frames[i], (size_t)lens[i], &pkt);
    if (r == 1) {
      got = 1;
    }
  }
  expect(got, "padded complete");
  expect(pkt.length == plen, "pad not extend");
  expect(memcmp(pkt.payload, payload, plen) == 0, "payload match");
  ilen = unhex("aab37116206425010a250000000000000000000000000000000000000000", info,
               sizeof(info));
  expect(decode_capabilities(info, ilen, &caps) == 0, "a7 caps");
  expect(decode_packet(&pkt, &caps, &dec) == 0, "decode a7");
  expect(dec.type == PKT_MEASUREMENT, "a7 type");
  expect(dec.weight_g == 75000, "a7 grams");
  expect(dec.has_device_time && dec.device_time == 0x12345678, "device_time");
}

static void test_capture_pairing(void) {
  packet_decoder_t decoder;
  packet_t info = {.sequence = 2, .unit = 1};
  packet_t measurement = {.sequence = 8, .unit = 1};
  packet_t pending;
  decoded_t decoded;
  int released;
  info.length = (uint16_t)unhex(
      "aab37116206425010a250000000000000000000000000000000000000000",
      info.payload, sizeof(info.payload));
  measurement.length = (uint16_t)unhex(
      "a712345678250124f8000a03e807d00bb80fa0138817701b581f4023282710ffffffff000000",
      measurement.payload, sizeof(measurement.payload));

  packet_decoder_init(&decoder);
  expect(packet_decoder_feed(&decoder, &measurement, &decoded, &released) == 0 &&
             !released,
         "early measurement waits for information");
  expect(packet_decoder_feed(&decoder, &info, &decoded, &released) == 0 && released,
         "matching information releases pending measurements");
  expect(packet_decoder_flush(&decoder, &pending, &decoded) &&
             decoded.type == PKT_MEASUREMENT && decoded.weight_g == 75000 &&
             pending.sequence == 8 && pending.unit == 1,
         "delayed capture preserves measurement and transport identity");
  expect(decoder.device_info.length == info.length &&
             memcmp(decoder.device_info.payload, info.payload, info.length) == 0 &&
             decoder.device_info.sequence == info.sequence &&
             decoder.device_info.unit == info.unit,
         "delayed capture retains complete interpreting information packet");

  packet_decoder_init(&decoder);
  expect(packet_decoder_feed(&decoder, &measurement, &decoded, &released) == 0 &&
             !released && decoder.device_info.length == 0,
         "new session cannot use old information");
  info.length = PAYLOAD_MAX + 1;
  expect(decode_packet(&info, NULL, &decoded) != 0,
         "oversized information cannot reach raw packet retention");
}

static void test_outbox_replay(void) {
  outbox_t box;
  char     id1[65];
  char     id2[65];
  packet_t p1 = {.length = 6, .payload = {0xa7, 1, 2, 3, 4, 5}, .unit = 1};
  packet_t p2 = {.length = 4, .payload = {0xa7, 9, 9, 9}, .unit = 1};
  packet_t info = {.sequence = 0, .unit = 1};
  int      idx;
  info.length = (uint16_t)unhex(
      "aab37116206425010a250000000000000000000000000000000000000000",
      info.payload, sizeof(info.payload));

  outbox_init(&box);
  expect(outbox_enqueue(&box, &p1, &info, 75000, id1) == ENQUEUE_NEW,
         "enq new");
  expect(outbox_enqueue(&box, &p1, &info, 75000, id2) == ENQUEUE_DUP,
         "retransmit same event");
  expect(strcmp(id1, id2) == 0, "stable id");
  {
    expect(outbox_find_sendable(&box, &idx), "sendable");
    expect(!http_response_accepts(200, "{\"eventId\":\"x\",\"status\":\"recorded\"}", id1),
           "mismatch retain");
    expect(!http_response_accepts(500, "{\"eventId\":\"x\",\"status\":\"recorded\"}", id1),
           "500 retain");
    expect(!http_response_accepts(200, "{\"eventId\":\"x\"}", id1), "ambiguous retain");
    expect(!http_response_accepts(200,
                                  "{\"nested\":{\"eventId\":\"x\",\"status\":\"recorded\"}}",
                                  id1),
           "nested reject");
    expect(!http_response_accepts(200, "{\"eventId\":\"x\",\"status\":\"recorded\"", id1),
           "truncated reject");
    expect(!http_response_accepts(
               200, "{\"eventId\":\"x\",\"status\":\"recorded\",\"eventId\":\"y\"}", id1),
           "dup key reject");
    expect(http_response_accepts(200,
                                 "{\"eventId\":\"PLACE\",\"status\":\"duplicate\"}", id1) == 0,
           "wrong id");
    {
      char body[256];
      snprintf(body, sizeof(body),
               "{\"eventId\":\"%s\",\"status\":\"recorded\",\"measuredOn\":\"2026-01-02\","
               "\"weightPounds\":165.3}",
               id1);
      expect(http_response_accepts(200, body, id1), "accept recorded");
      expect(outbox_accept_http(&box, &box.records[idx], "recorded"), "dequeue");
      expect(outbox_queued_count(&box) == 0, "dequeued");
      expect(outbox_enqueue(&box, &p1, &info, 75000, id2) == ENQUEUE_DUP,
             "delivered retransmission stays acknowledged");
      expect(outbox_queued_count(&box) == 0, "delivered retransmission is not requeued");
    }
  }
  outbox_init(&box);
  {
    int i;
    for (i = 0; i < OUTBOX_CAP; i++) {
      packet_t p = {.length = 2, .payload = {0xa7, (uint8_t)i}, .unit = 1};
      char    id[65];
      expect(outbox_enqueue(&box, &p, &info, 1000 + (uint32_t)i, id) == ENQUEUE_NEW,
             "fill");
    }
    expect(outbox_enqueue(&box, &p2, &info, 1, id1) ==
               ENQUEUE_FULL,
           "full no ack");
  }
  outbox_init(&box);
  expect(outbox_latest(&box) == NULL, "empty box has no latest");
  expect(outbox_enqueue(&box, &p1, &info, 1, id1) == ENQUEUE_NEW, "1g reading");
  expect(outbox_find_sendable(&box, &idx) && idx == 0, "every new reading is sendable");
  expect(outbox_enqueue(&box, &p2, &info, 2, id2) == ENQUEUE_NEW, "2g reading");
  expect(outbox_latest(&box) && outbox_latest(&box)->weight_grams == 2, "latest is newest");
  expect(outbox_enqueue(&box, &p1, &info, 1, id1) == ENQUEUE_DUP, "older dup");
  expect(outbox_latest(&box)->weight_grams == 2, "dup does not become latest");
}

static void test_json_edges(void) {
  usb_config_t cfg;
  char         err[80];
  char         cmd[32];
  const char  *escaped =
      "{\"command\":\"configure\",\"deviceId\":\"relay-1\",\"receiverUrl\":\"http://"
      "192.168.1.2:8080\",\"scaleAddress\":\"aa:bb:cc:dd:ee:ff\","
      "\"wifiSsid\":\"caf\\u00e9\",\"wifiPassword\":\"p\\\"ass\\\\word\"}";
  const char *dup_field =
      "{\"command\":\"configure\",\"deviceId\":\"relay-1\",\"receiverUrl\":\"http://"
      "192.168.1.2:8080\",\"scaleAddress\":\"aa:bb:cc:dd:ee:ff\","
      "\"wifiSsid\":\"lan\",\"wifiPassword\":\"secret\",\"wifiSsid\":\"other\"}";
  const char *tail =
      "{\"command\":\"configure\",\"deviceId\":\"relay-1\"} trailing";
  const char *nul_s = "{\"command\":\"a\\u0000b\"}";

  expect(usb_parse_configure(escaped, &cfg, err, sizeof(err)), "escaped cfg");
  expect(strcmp(cfg.wifi_ssid, "caf\xC3\xA9") == 0, "unicode ssid");
  expect(strcmp(cfg.wifi_password, "p\"ass\\word") == 0, "escaped password");
  expect(!usb_parse_configure(dup_field, &cfg, err, sizeof(err)), "dup field");
  expect(!http_extract_json_string(tail, "command", cmd, sizeof(cmd)), "malformed tail");
  expect(!http_extract_json_string(nul_s, "command", cmd, sizeof(cmd)), "embedded nul");
  expect(!http_response_accepts(200, "{\"eventId\":\"x\",\"status\":\"recorded\"}x", "x"),
         "ack junk");
  expect(!http_response_accepts(200, "{\"eventId\":\"x\",\"status\":true}", "x"),
         "ack status type");
  expect(http_response_accepts(
             200, "{\"eventId\":\"x\",\"status\":\"recorded\",\"extra\":{\"eventId\":\"y\"}}",
             "x"),
         "nested extra ignored");
  expect(!http_response_accepts(200, "{\"eventId\":\"x\",\"status\":\"recorded\",\"n\":01}",
                               "x"),
         "leading zero number");
  expect(http_response_accepts(
             200, "{\"eventId\":\"x\",\"status\":\"superseded\",\"n\":1.5e-2}", "x"),
         "exponent number");
}

static void test_usb_and_render(void) {
  usb_config_t cfg;
  char         err[80];
  uint16_t     fb[LCD_W * LCD_H];
  ui_model_t   model;
  const char  *ok =
      "{\"command\":\"configure\",\"deviceId\":\"relay-1\",\"receiverUrl\":\"http://"
      "192.168.1.2:8080\",\"scaleAddress\":\"aa:bb:cc:dd:ee:ff\","
      "\"wifiSsid\":\"lan\",\"wifiPassword\":\"secret\"}";

  expect(usb_parse_configure(ok, &cfg, err, sizeof(err)), "cfg ok");
  expect(!usb_parse_configure("I (123) wifi: connected", &cfg, err, sizeof(err)),
         "survive log line");
  expect(!validate_receiver_url("http://user:pass@host"), "no creds in url");
  expect(validate_scale_address(""), "empty scale address means auto-pair");
  expect(validate_scale_address("AA:bb:CC:dd:EE:ff"), "mac scale address");
  expect(!validate_scale_address("AA:BB:CC:DD:EE"), "short scale address");
  expect(scale_name_matches((const uint8_t *)"R-MSC01", 7), "scale name");
  expect(!scale_name_matches((const uint8_t *)"R-MSC011", 8), "longer name");
  expect(!scale_name_matches((const uint8_t *)"R-MSC0", 6), "prefix name");
  expect(!scale_name_matches(NULL, 0), "no name");
  expect(usb_parse_configure(
             "{\"command\":\"configure\",\"deviceId\":\"relay-1\",\"receiverUrl\":\"http://"
             "192.0.2.10:8080\",\"scaleAddress\":\"\",\"wifiSsid\":\"lan\",\"wifiPassword\":\"\"}",
             &cfg, err, sizeof(err)) && cfg.scale_address[0] == 0,
         "configure without scale address");
  memset(&model, 0, sizeof(model));
  model.state       = UI_QUEUED;
  model.has_weight  = 1;
  model.weight_grams = 75000;
  model.queued = 1;
  render_frame(fb, &model);
  expect(render_ppm(fb, "relay-frame.ppm") == 0, "ppm");
  {
    static uint16_t with_weight[LCD_W * LCD_H];
    static uint16_t without_weight[LCD_W * LCD_H];
    model.state = UI_PAIRING;
    render_frame(with_weight, &model);
    model.has_weight = 0;
    render_frame(without_weight, &model);
    expect(memcmp(with_weight, without_weight, sizeof(with_weight)) == 0,
           "pairing screen hides the stored weight");
    expect(memcmp(with_weight, fb, sizeof(fb)) != 0, "pairing screen differs from queued screen");
    expect(render_ppm(with_weight, "relay-pairing.ppm") == 0, "pairing ppm");
  }
}

int main(void) {
  test_bluetooth_uuid();
  test_reassembly();
  test_padded_a7();
  test_capture_pairing();
  test_outbox_replay();
  test_json_edges();
  test_usb_and_render();
  failures += verify_outbox_packets();
  failures += verify_upload_packets();
  if (failures) {
    fprintf(stderr, "%d failures\n", failures);
    return 1;
  }
  puts("ok");
  return 0;
}
