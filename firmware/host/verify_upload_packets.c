#include "http_parse.h"

#include <stdio.h>
#include <string.h>

static void fail_msg(int *failures, int cond, const char *msg) {
  if (!cond) {
    fprintf(stderr, "verify_upload_packets: %s\n", msg);
    (*failures)++;
  }
}

static void fill_hex_id(char *id) {
  memset(id, '1', 64);
  id[64] = 0;
}

static void init_rec(outbox_record_t *rec) {
  memset(rec, 0, sizeof(*rec));
  fill_hex_id(rec->event_id);
  rec->weight_grams = 75000;
}

int verify_upload_packets(void) {
  int             failures = 0;
  outbox_record_t rec;
  char            body[HTTP_READING_MAX + 1];
  int             n;

  init_rec(&rec);
  n = http_format_reading(body, sizeof(body), "relay-1", &rec);
  fail_msg(&failures, n > 0 && strstr(body, "\"scaleMeasurement\"") == NULL,
           "legacy readings remain sendable without invented packets");
  fail_msg(&failures, strstr(body, "measuredAt") == NULL, "relay sends no measurement time");

  init_rec(&rec);
  memset(rec.device_info.payload, 0x5a, PAYLOAD_MAX);
  rec.device_info.length   = PAYLOAD_MAX;
  rec.device_info.sequence = 255;
  rec.device_info.unit     = 7;
  memset(rec.measurement.payload, 0x00, PAYLOAD_MAX);
  rec.measurement.payload[0]               = 0xa7;
  rec.measurement.payload[PAYLOAD_MAX - 1] = 0x0d;
  rec.measurement.length                   = PAYLOAD_MAX;
  rec.measurement.sequence                 = 1;
  rec.measurement.unit                     = 0;
  n = http_format_reading(body, sizeof(body), "relay-1", &rec);
  fail_msg(&failures, n > 0 && n < HTTP_READING_MAX, "max packets fit HTTP_READING_MAX");
  fail_msg(&failures, (size_t)n == strlen(body), "NUL excluded from count");
  {
    char tight[HTTP_READING_MAX + 1];
    int  n2 = http_format_reading(tight, (size_t)n, "relay-1", &rec);
    int  n3 = http_format_reading(tight, (size_t)n + 1, "relay-1", &rec);
    fail_msg(&failures, n2 == 0, "capacity == n truncates");
    fail_msg(&failures, n3 == n, "capacity == n+1 exact");
  }

  init_rec(&rec);
  rec.device_info.length = 1;
  rec.device_info.unit   = 0;
  rec.measurement.length = 1;
  rec.measurement.unit   = 8;
  fail_msg(&failures, http_format_reading(body, sizeof(body), "relay-1", &rec) == 0,
           "unit 8 rejected");

  init_rec(&rec);
  rec.device_info.length = 1;
  rec.measurement.length = 0;
  fail_msg(&failures, http_format_reading(body, sizeof(body), "relay-1", &rec) == 0,
           "missing measurement rejected");

  init_rec(&rec);
  rec.device_info.length = 0;
  rec.measurement.length = 1;
  fail_msg(&failures, http_format_reading(body, sizeof(body), "relay-1", &rec) == 0,
           "missing device_info rejected");

  init_rec(&rec);
  rec.device_info.length = PAYLOAD_MAX + 1;
  rec.device_info.unit   = 0;
  rec.measurement.length = 1;
  rec.measurement.unit   = 0;
  fail_msg(&failures, http_format_reading(body, sizeof(body), "relay-1", &rec) == 0,
           "oversize length rejected");

  init_rec(&rec);
  fail_msg(&failures, http_format_reading(body, sizeof(body), "bad\"id", &rec) == 0,
           "unsafe deviceId rejected");
  fail_msg(&failures, http_format_reading(NULL, sizeof(body), "relay-1", &rec) == 0,
           "null out rejected");

  return failures;
}
