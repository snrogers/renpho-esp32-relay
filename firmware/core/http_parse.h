#ifndef RELAY_HTTP_PARSE_H
#define RELAY_HTTP_PARSE_H

#include "outbox.h"
#include "protocol.h"

#include <stddef.h>

enum { HTTP_READING_MAX = 8 * PAYLOAD_MAX + 1024 };

int http_extract_json_string(const char *json, const char *key, char *out, int out_len);
int http_format_reading(char *out, size_t capacity, const char *device_id,
                        const outbox_record_t *rec);
int http_response_accepts(int status_code, const char *body, const char *expect_event_id);

#endif
