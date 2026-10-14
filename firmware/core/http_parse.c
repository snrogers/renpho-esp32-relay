#include "http_parse.h"

#include "config_validate.h"

#include <stdio.h>
#include <string.h>

enum { JSON_MAX_DEPTH = 8 };

static const char *skip_ws(const char *p) {
  while (p && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) {
    p++;
  }
  return p;
}

static int hex_nibble(char c) {
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

static int parse_hex4(const char **pp, unsigned *out) {
  const char *p = *pp;
  unsigned    v = 0;
  int         i;

  for (i = 0; i < 4; i++) {
    int n = hex_nibble(p[i]);
    if (n < 0) {
      return 0;
    }
    v = (v << 4) | (unsigned)n;
  }
  *out = v;
  *pp  = p + 4;
  return 1;
}

static int utf8_append(char *out, int out_len, int *n, unsigned cp) {
  unsigned char buf[4];
  int           k;
  int           i;

  if (cp > 0x10FFFFu || (cp >= 0xD800u && cp <= 0xDFFFu)) {
    return 0;
  }
  if (cp == 0) {
    return -1;
  }
  if (cp < 0x80u) {
    buf[0] = (unsigned char)cp;
    k      = 1;
  } else if (cp < 0x800u) {
    buf[0] = (unsigned char)(0xC0u | (cp >> 6));
    buf[1] = (unsigned char)(0x80u | (cp & 0x3Fu));
    k      = 2;
  } else if (cp < 0x10000u) {
    buf[0] = (unsigned char)(0xE0u | (cp >> 12));
    buf[1] = (unsigned char)(0x80u | ((cp >> 6) & 0x3Fu));
    buf[2] = (unsigned char)(0x80u | (cp & 0x3Fu));
    k      = 3;
  } else {
    buf[0] = (unsigned char)(0xF0u | (cp >> 18));
    buf[1] = (unsigned char)(0x80u | ((cp >> 12) & 0x3Fu));
    buf[2] = (unsigned char)(0x80u | ((cp >> 6) & 0x3Fu));
    buf[3] = (unsigned char)(0x80u | (cp & 0x3Fu));
    k      = 4;
  }
  if (!out) {
    return 1;
  }
  if (*n + k >= out_len) {
    return 0;
  }
  for (i = 0; i < k; i++) {
    out[(*n)++] = (char)buf[i];
  }
  return 1;
}

static int utf8_raw_len(const unsigned char *p) {
  unsigned char c = p[0];
  int           n;
  int           i;

  if (c < 0x80u) {
    if (c < 0x20u) {
      return 0;
    }
    return 1;
  }
  if ((c & 0xE0u) == 0xC0u) {
    n = 2;
    if (c < 0xC2u) {
      return 0;
    }
  } else if ((c & 0xF0u) == 0xE0u) {
    n = 3;
  } else if ((c & 0xF8u) == 0xF0u) {
    n = 4;
    if (c > 0xF4u) {
      return 0;
    }
  } else {
    return 0;
  }
  for (i = 1; i < n; i++) {
    if ((p[i] & 0xC0u) != 0x80u) {
      return 0;
    }
  }
  if (n == 3) {
    unsigned cp = ((unsigned)(c & 0x0Fu) << 12) | ((unsigned)(p[1] & 0x3Fu) << 6) |
                  (unsigned)(p[2] & 0x3Fu);
    if (cp < 0x800u || (cp >= 0xD800u && cp <= 0xDFFFu)) {
      return 0;
    }
  }
  if (n == 4) {
    unsigned cp = ((unsigned)(c & 0x07u) << 18) | ((unsigned)(p[1] & 0x3Fu) << 12) |
                  ((unsigned)(p[2] & 0x3Fu) << 6) | (unsigned)(p[3] & 0x3Fu);
    if (cp < 0x10000u || cp > 0x10FFFFu) {
      return 0;
    }
  }
  return n;
}

static int parse_string(const char **pp, char *out, int out_len) {
  const char *p = *pp;
  int         n = 0;
  int         saw_nul = 0;

  if (*p != '"') {
    return 0;
  }
  p++;
  while (*p && *p != '"') {
    if ((unsigned char)*p < 0x20) {
      return 0;
    }
    if (*p == '\\') {
      unsigned cp;
      int      put;

      p++;
      if (!*p) {
        return 0;
      }
      switch (*p) {
      case '"':
      case '\\':
      case '/':
        put = utf8_append(out, out_len, &n, (unsigned char)*p);
        p++;
        break;
      case 'b':
        put = utf8_append(out, out_len, &n, 0x08);
        p++;
        break;
      case 'f':
        put = utf8_append(out, out_len, &n, 0x0C);
        p++;
        break;
      case 'n':
        put = utf8_append(out, out_len, &n, 0x0A);
        p++;
        break;
      case 'r':
        put = utf8_append(out, out_len, &n, 0x0D);
        p++;
        break;
      case 't':
        put = utf8_append(out, out_len, &n, 0x09);
        p++;
        break;
      case 'u':
        p++;
        if (!parse_hex4(&p, &cp)) {
          return 0;
        }
        if (cp >= 0xD800u && cp <= 0xDBFFu) {
          unsigned low;

          if (p[0] != '\\' || p[1] != 'u') {
            return 0;
          }
          p += 2;
          if (!parse_hex4(&p, &low) || low < 0xDC00u || low > 0xDFFFu) {
            return 0;
          }
          cp = 0x10000u + (((cp - 0xD800u) << 10) | (low - 0xDC00u));
        } else if (cp >= 0xDC00u && cp <= 0xDFFFu) {
          return 0;
        }
        put = utf8_append(out, out_len, &n, cp);
        break;
      default:
        return 0;
      }
      if (put == -1) {
        saw_nul = 1;
        continue;
      }
      if (!put) {
        return 0;
      }
      continue;
    } else {
      int k = utf8_raw_len((const unsigned char *)p);
      int i;

      if (k <= 0) {
        return 0;
      }
      if (out) {
        if (n + k >= out_len) {
          return 0;
        }
        for (i = 0; i < k; i++) {
          out[n++] = p[i];
        }
      }
      p += k;
    }
  }
  if (*p != '"') {
    return 0;
  }
  if (out) {
    if (saw_nul) {
      return 0;
    }
    out[n] = 0;
  }
  *pp = p + 1;
  return 1;
}

static int parse_number(const char **pp) {
  const char *p = *pp;

  if (*p == '-') {
    p++;
  }
  if (*p == '0') {
    p++;
  } else if (*p >= '1' && *p <= '9') {
    while (*p >= '0' && *p <= '9') {
      p++;
    }
  } else {
    return 0;
  }
  if (*p == '.') {
    p++;
    if (*p < '0' || *p > '9') {
      return 0;
    }
    while (*p >= '0' && *p <= '9') {
      p++;
    }
  }
  if (*p == 'e' || *p == 'E') {
    p++;
    if (*p == '+' || *p == '-') {
      p++;
    }
    if (*p < '0' || *p > '9') {
      return 0;
    }
    while (*p >= '0' && *p <= '9') {
      p++;
    }
  }
  *pp = p;
  return 1;
}

static int skip_value(const char **pp, int depth);

static int skip_object_or_array(const char **pp, int depth, char open, char close) {
  const char *p     = *pp;
  int         first = 1;

  if (depth >= JSON_MAX_DEPTH) {
    return 0;
  }
  if (*p != open) {
    return 0;
  }
  p++;
  p = skip_ws(p);
  while (*p && *p != close) {
    if (!first) {
      if (*p != ',') {
        return 0;
      }
      p++;
      p = skip_ws(p);
      if (*p == close) {
        return 0;
      }
    }
    first = 0;
    if (open == '{') {
      if (!parse_string(&p, NULL, 0)) {
        return 0;
      }
      p = skip_ws(p);
      if (*p != ':') {
        return 0;
      }
      p++;
      p = skip_ws(p);
    }
    if (!skip_value(&p, depth + 1)) {
      return 0;
    }
    p = skip_ws(p);
  }
  if (*p != close) {
    return 0;
  }
  *pp = p + 1;
  return 1;
}

static int skip_value(const char **pp, int depth) {
  const char *p = *pp;

  if (*p == '"') {
    return parse_string(pp, NULL, 0);
  }
  if (*p == '{') {
    return skip_object_or_array(pp, depth, '{', '}');
  }
  if (*p == '[') {
    return skip_object_or_array(pp, depth, '[', ']');
  }
  if (!strncmp(p, "true", 4)) {
    *pp = p + 4;
    return 1;
  }
  if (!strncmp(p, "false", 5)) {
    *pp = p + 5;
    return 1;
  }
  if (!strncmp(p, "null", 4)) {
    *pp = p + 4;
    return 1;
  }
  return parse_number(pp);
}

static int finish_document(const char *p) {
  p = skip_ws(p);
  return *p == 0;
}

typedef struct {
  char event_id[129];
  char status[32];
  int  have_event;
  int  have_status;
} json_ack_t;

static int parse_object_ack(const char *json, json_ack_t *ack) {
  const char *p     = skip_ws(json);
  int         first = 1;

  memset(ack, 0, sizeof(*ack));
  if (!p || *p != '{') {
    return 0;
  }
  p++;
  p = skip_ws(p);
  while (*p && *p != '}') {
    char key[40];

    if (!first) {
      if (*p != ',') {
        return 0;
      }
      p++;
      p = skip_ws(p);
      if (*p == '}') {
        return 0;
      }
    }
    first = 0;
    if (!parse_string(&p, key, sizeof(key))) {
      return 0;
    }
    p = skip_ws(p);
    if (*p != ':') {
      return 0;
    }
    p++;
    p = skip_ws(p);
    if (strcmp(key, "eventId") == 0) {
      char value[129];
      if (!parse_string(&p, value, sizeof(value))) {
        return 0;
      }
      if (ack->have_event) {
        return 0;
      }
      memcpy(ack->event_id, value, sizeof(ack->event_id));
      ack->have_event = 1;
    } else if (strcmp(key, "status") == 0) {
      char value[32];
      if (!parse_string(&p, value, sizeof(value))) {
        return 0;
      }
      if (ack->have_status) {
        return 0;
      }
      memcpy(ack->status, value, sizeof(ack->status));
      ack->have_status = 1;
    } else {
      if (!skip_value(&p, 1)) {
        return 0;
      }
    }
    p = skip_ws(p);
  }
  if (*p != '}') {
    return 0;
  }
  if (!finish_document(p + 1)) {
    return 0;
  }
  return 1;
}

int http_extract_json_string(const char *json, const char *key, char *out, int out_len) {
  const char *p;
  int         first = 1;
  int         found = 0;
  char        value[257];

  if (!json || !key || !out || out_len < 2) {
    return 0;
  }
  p = skip_ws(json);
  if (*p != '{') {
    return 0;
  }
  p++;
  p = skip_ws(p);
  while (*p && *p != '}') {
    char name[80];

    if (!first) {
      if (*p != ',') {
        return 0;
      }
      p++;
      p = skip_ws(p);
      if (*p == '}') {
        return 0;
      }
    }
    first = 0;
    if (!parse_string(&p, name, sizeof(name))) {
      return 0;
    }
    p = skip_ws(p);
    if (*p != ':') {
      return 0;
    }
    p++;
    p = skip_ws(p);
    if (strcmp(name, key) == 0) {
      if (found) {
        return 0;
      }
      if (!parse_string(&p, value, sizeof(value))) {
        return 0;
      }
      found = 1;
    } else if (!skip_value(&p, 1)) {
      return 0;
    }
    p = skip_ws(p);
  }
  if (*p != '}') {
    return 0;
  }
  if (!finish_document(p + 1)) {
    return 0;
  }
  if (!found) {
    return 0;
  }
  if ((int)strlen(value) >= out_len) {
    return 0;
  }
  memcpy(out, value, strlen(value) + 1);
  return 1;
}

int http_response_accepts(int status_code, const char *body, const char *expect_event_id) {
  json_ack_t ack;

  if (status_code != 200 || !body || !expect_event_id) {
    return 0;
  }
  if (!parse_object_ack(body, &ack)) {
    return 0;
  }
  if (!ack.have_event || !ack.have_status) {
    return 0;
  }
  if (strcmp(ack.event_id, expect_event_id) != 0) {
    return 0;
  }
  return strcmp(ack.status, "recorded") == 0 || strcmp(ack.status, "duplicate") == 0 ||
         strcmp(ack.status, "superseded") == 0;
}

static int json_text_ok(const char *s) {
  size_t i;
  if (!s) {
    return 0;
  }
  for (i = 0; s[i]; i++) {
    unsigned char c = (unsigned char)s[i];
    if (c < 0x20 || c == '"' || c == '\\') {
      return 0;
    }
  }
  return 1;
}

static int event_id_ok(const char *s) {
  size_t i;
  if (!s || strlen(s) != 64) {
    return 0;
  }
  for (i = 0; i < 64; i++) {
    char c = s[i];
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) {
      return 0;
    }
  }
  return 1;
}

static int packet_ok(const packet_t *pkt) {
  return pkt && pkt->length >= 1 && pkt->length <= PAYLOAD_MAX && pkt->unit <= 7;
}

static int append_raw(char *out, size_t cap, size_t *n, const char *s, size_t len) {
  if (!out || *n >= cap || len >= cap - *n) {
    return 0;
  }
  memcpy(out + *n, s, len);
  *n += len;
  out[*n] = 0;
  return 1;
}

static int append_str(char *out, size_t cap, size_t *n, const char *s) {
  return s && append_raw(out, cap, n, s, strlen(s));
}

static int append_hex(char *out, size_t cap, size_t *n, const uint8_t *bytes, uint16_t len) {
  static const char hex[]   = "0123456789abcdef";
  size_t            encoded = (size_t)len * 2;
  if (!bytes || *n >= cap || encoded >= cap - *n) {
    return 0;
  }
  for (size_t i = 0; i < len; i++) {
    out[*n + i * 2]     = hex[bytes[i] >> 4];
    out[*n + i * 2 + 1] = hex[bytes[i] & 15];
  }
  *n += encoded;
  out[*n] = 0;
  return 1;
}

static int append_u32(char *out, size_t cap, size_t *n, unsigned v) {
  char tmp[16];
  int  w = snprintf(tmp, sizeof(tmp), "%u", v);
  if (w <= 0 || (size_t)w >= sizeof(tmp)) {
    return 0;
  }
  return append_raw(out, cap, n, tmp, (size_t)w);
}

static int append_quoted(char *out, size_t cap, size_t *n, const char *s) {
  return append_str(out, cap, n, "\"") && append_str(out, cap, n, s) &&
         append_str(out, cap, n, "\"");
}

static int append_packet_obj(char *out, size_t cap, size_t *n, const packet_t *pkt) {
  return append_str(out, cap, n, "{\"payloadHex\":\"") &&
         append_hex(out, cap, n, pkt->payload, pkt->length) &&
         append_str(out, cap, n, "\",\"sequence\":") && append_u32(out, cap, n, pkt->sequence) &&
         append_str(out, cap, n, ",\"unit\":") && append_u32(out, cap, n, pkt->unit) &&
         append_str(out, cap, n, "}");
}

int http_format_reading(char *out, size_t capacity, const char *device_id,
                        const outbox_record_t *rec) {
  size_t n = 0;
  int    have_packets;

  if (!out || capacity < 2 || !rec) {
    return 0;
  }
  out[0] = 0;
  if (!validate_device_id(device_id) || !json_text_ok(device_id) || !event_id_ok(rec->event_id)) {
    return 0;
  }
  have_packets = rec->device_info.length != 0 || rec->measurement.length != 0;
  if (have_packets && (!packet_ok(&rec->device_info) || !packet_ok(&rec->measurement))) {
    return 0;
  }
  if (!append_str(out, capacity, &n, "{\"deviceId\":") ||
      !append_quoted(out, capacity, &n, device_id) ||
      !append_str(out, capacity, &n, ",\"eventId\":") ||
      !append_quoted(out, capacity, &n, rec->event_id) ||
      !append_str(out, capacity, &n, ",\"weightGrams\":") ||
      !append_u32(out, capacity, &n, rec->weight_grams)) {
    return 0;
  }
  if (have_packets) {
    if (!append_str(out, capacity, &n, ",\"scaleMeasurement\":{\"deviceInfoPayloadHex\":\"") ||
        !append_hex(out, capacity, &n, rec->device_info.payload, rec->device_info.length) ||
        !append_str(out, capacity, &n, "\",\"measurementPayloadHex\":\"") ||
        !append_hex(out, capacity, &n, rec->measurement.payload, rec->measurement.length) ||
        !append_str(out, capacity, &n, "\",\"sequence\":") ||
        !append_u32(out, capacity, &n, rec->measurement.sequence) ||
        !append_str(out, capacity, &n, ",\"unit\":") ||
        append_u32(out, capacity, &n, rec->measurement.unit) == 0 ||
        !append_str(out, capacity, &n, ",\"rawPackets\":[") ||
        !append_packet_obj(out, capacity, &n, &rec->device_info) ||
        !append_str(out, capacity, &n, ",") ||
        !append_packet_obj(out, capacity, &n, &rec->measurement) ||
        !append_str(out, capacity, &n, "]}")) {
      return 0;
    }
  }
  if (!append_str(out, capacity, &n, "}")) {
    return 0;
  }
  return (int)n;
}
