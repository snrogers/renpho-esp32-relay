#ifndef RELAY_OUTBOX_H
#define RELAY_OUTBOX_H

#include "protocol.h"

#include <stddef.h>
#include <stdint.h>

enum {
  OUTBOX_CAP         = 16,
  EVENT_ID_LEN       = 65,
  OUTBOX_FORMAT      = 0x3358424F,
  OUTBOX_OBX2_FORMAT = 0x3258424F,
  OUTBOX_OBX2_SIZE   = 19080,
  OUTBOX_LEGACY_SIZE = 2564
};

typedef enum { OUTBOX_QUEUED = 0, OUTBOX_DELIVERED } outbox_state_t;

/* OBX3 flash layout: preserve this field order; changes require a migration. */
typedef struct {
  char     event_id[EVENT_ID_LEN];
  uint32_t weight_grams;
  uint8_t  payload_hash[32];
  uint8_t  occupied;
  uint8_t  state;
  packet_t device_info;
  packet_t measurement;
} outbox_record_t;

typedef struct {
  uint32_t        format;
  outbox_record_t records[OUTBOX_CAP];
  int             count;
  int             latest;
} outbox_t;

typedef enum {
  ENQUEUE_NEW = 0,
  ENQUEUE_DUP,
  ENQUEUE_FULL,
  ENQUEUE_FAIL,
  ENQUEUE_ENRICHED
} enqueue_result_t;

void outbox_init(outbox_t *box);

enqueue_result_t outbox_enqueue(outbox_t *box, const packet_t *measurement,
                                const packet_t *device_info, uint32_t weight_grams,
                                char event_id[EVENT_ID_LEN]);

/* Old-format blobs must not overlap box; an OBX3 blob may. */
int outbox_restore(outbox_t *box, const void *blob, size_t length);

int outbox_find_sendable(const outbox_t *box, int *index);
int outbox_accept_http(outbox_t *box, const outbox_record_t *sent, const char *status);
int outbox_queued_count(const outbox_t *box);
const outbox_record_t *outbox_latest(const outbox_t *box);

#endif
