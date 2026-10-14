#include "outbox.h"

#include "sha256.h"

#include <stddef.h>
#include <string.h>

/* Pre-OBX3 records carried a capture time; migration keeps only its order. */
typedef struct {
  char     event_id[EVENT_ID_LEN];
  char     measured_at[48];
  uint32_t weight_grams;
  uint32_t capture_unix;
  uint8_t  payload_hash[32];
  uint8_t  dated;
  uint8_t  occupied;
  uint8_t  state;
} legacy_record_t;

typedef struct {
  legacy_record_t head;
  packet_t        device_info;
  packet_t        measurement;
} obx2_record_t;

typedef struct {
  legacy_record_t records[OUTBOX_CAP];
  int             count;
} legacy_outbox_t;

typedef struct {
  uint32_t      format;
  obx2_record_t records[OUTBOX_CAP];
  int           count;
} obx2_outbox_t;

_Static_assert(sizeof(legacy_record_t) == 160, "legacy record ABI");
_Static_assert(sizeof(legacy_outbox_t) == OUTBOX_LEGACY_SIZE, "legacy outbox ABI");
_Static_assert(sizeof(obx2_record_t) == 1192, "OBX2 record ABI");
_Static_assert(sizeof(obx2_outbox_t) == OUTBOX_OBX2_SIZE, "OBX2 outbox ABI");
_Static_assert(sizeof(outbox_record_t) == 1140, "record ABI");
_Static_assert(sizeof(outbox_t) == 18252, "outbox ABI");
_Static_assert(offsetof(outbox_t, format) == 0, "format leads blob");
_Static_assert(offsetof(outbox_t, records) == 4, "records follow format");
_Static_assert(offsetof(outbox_t, count) == 4 + sizeof(outbox_record_t) * OUTBOX_CAP,
               "count trails records");
_Static_assert(offsetof(outbox_t, latest) == offsetof(outbox_t, count) + sizeof(int),
               "latest trails count");

void outbox_init(outbox_t *box) {
  memset(box, 0, sizeof(*box));
  box->format = OUTBOX_FORMAT;
  box->latest = -1;
}

static int hash_equal(const uint8_t a[32], const uint8_t b[32]) { return memcmp(a, b, 32) == 0; }

static int packet_ok(const packet_t *p) {
  return p && p->length >= 1 && p->length <= PAYLOAD_MAX && p->unit <= 7;
}

static void copy_packet(packet_t *dst, const packet_t *src) {
  memset(dst, 0, sizeof(*dst));
  dst->length   = src->length;
  dst->sequence = src->sequence;
  dst->unit     = src->unit;
  memcpy(dst->payload, src->payload, src->length);
}

static int packets_empty(const outbox_record_t *rec) {
  return rec->device_info.length == 0 && rec->measurement.length == 0;
}

static int terminated(const char *s, size_t n) { return memchr(s, 0, n) != NULL; }

static int packet_stored_ok(const packet_t *p) {
  uint16_t i;

  if (p->length == 0) {
    if (p->sequence != 0 || p->unit != 0) {
      return 0;
    }
    for (i = 0; i < PAYLOAD_MAX; i++) {
      if (p->payload[i] != 0) {
        return 0;
      }
    }
    return 1;
  }
  if (p->length > PAYLOAD_MAX || p->unit > 7) {
    return 0;
  }
  for (i = p->length; i < PAYLOAD_MAX; i++) {
    if (p->payload[i] != 0) {
      return 0;
    }
  }
  return 1;
}

static int packets_stored_ok(const packet_t *info, const packet_t *meas) {
  if ((info->length == 0) != (meas->length == 0)) {
    return 0;
  }
  return packet_stored_ok(info) && packet_stored_ok(meas);
}

static int state_ok(uint8_t occupied, uint8_t state) {
  return occupied <= 1 && (state == OUTBOX_QUEUED || state == OUTBOX_DELIVERED);
}

static int current_record_ok(const outbox_record_t *rec) {
  if (!state_ok(rec->occupied, rec->state)) {
    return 0;
  }
  if (!rec->occupied) {
    return 1;
  }
  if (!terminated(rec->event_id, EVENT_ID_LEN) || rec->weight_grams == 0) {
    return 0;
  }
  return packets_stored_ok(&rec->device_info, &rec->measurement);
}

static int current_ok(const outbox_t *box) {
  int occupied = 0;

  if (box->format != OUTBOX_FORMAT || box->count < 0 || box->count > OUTBOX_CAP) {
    return 0;
  }
  for (int i = 0; i < OUTBOX_CAP; i++) {
    if (!current_record_ok(&box->records[i])) {
      return 0;
    }
    occupied += box->records[i].occupied;
  }
  if (occupied != box->count) {
    return 0;
  }
  if (box->latest == -1) {
    return box->count == 0;
  }
  return box->latest >= 0 && box->latest < OUTBOX_CAP && box->records[box->latest].occupied;
}

static int legacy_record_ok(const legacy_record_t *rec) {
  if (!state_ok(rec->occupied, rec->state) || rec->dated > 1) {
    return 0;
  }
  if (!rec->occupied) {
    return 1;
  }
  if (!terminated(rec->event_id, EVENT_ID_LEN) || !terminated(rec->measured_at, 48)) {
    return 0;
  }
  return rec->weight_grams != 0;
}

static int legacy_ok(const legacy_outbox_t *old) {
  for (int i = 0; i < OUTBOX_CAP; i++) {
    if (!legacy_record_ok(&old->records[i])) {
      return 0;
    }
  }
  return 1;
}

static int obx2_ok(const obx2_outbox_t *old) {
  int occupied = 0;

  if (old->format != OUTBOX_OBX2_FORMAT || old->count < 0 || old->count > OUTBOX_CAP) {
    return 0;
  }
  for (int i = 0; i < OUTBOX_CAP; i++) {
    const obx2_record_t *rec = &old->records[i];
    if (!legacy_record_ok(&rec->head)) {
      return 0;
    }
    if (rec->head.occupied && !packets_stored_ok(&rec->device_info, &rec->measurement)) {
      return 0;
    }
    occupied += rec->head.occupied;
  }
  return occupied == old->count;
}

/* Copies one pre-OBX3 record. Returns its capture time for ordering, or -1. */
static int64_t migrate_record(outbox_record_t *out, const legacy_record_t *in) {
  memset(out, 0, sizeof(*out));
  if (!in->occupied) {
    return -1;
  }
  memcpy(out->event_id, in->event_id, EVENT_ID_LEN);
  out->weight_grams = in->weight_grams;
  memcpy(out->payload_hash, in->payload_hash, 32);
  out->occupied = 1;
  out->state    = in->state;
  return in->capture_unix;
}

static void note_migrated(outbox_t *box, int slot, int64_t order, int64_t *newest) {
  if (order < 0) {
    return;
  }
  box->count++;
  if (order >= *newest) {
    *newest     = order;
    box->latest = slot;
  }
}

int outbox_restore(outbox_t *box, const void *blob, size_t length) {
  int64_t newest = -1;

  if (!box || !blob) {
    return 0;
  }
  if (length == sizeof(outbox_t)) {
    if (!current_ok(blob)) {
      return 0;
    }
    memmove(box, blob, sizeof(*box));
    return 1;
  }
  if (length == sizeof(obx2_outbox_t)) {
    const obx2_outbox_t *old = blob;
    if (!obx2_ok(old)) {
      return 0;
    }
    outbox_init(box);
    for (int i = 0; i < OUTBOX_CAP; i++) {
      int64_t order = migrate_record(&box->records[i], &old->records[i].head);
      if (order >= 0) {
        copy_packet(&box->records[i].device_info, &old->records[i].device_info);
        copy_packet(&box->records[i].measurement, &old->records[i].measurement);
      }
      note_migrated(box, i, order, &newest);
    }
    return 1;
  }
  if (length == sizeof(legacy_outbox_t)) {
    const legacy_outbox_t *old = blob;
    if (!legacy_ok(old)) {
      return 0;
    }
    outbox_init(box);
    for (int i = 0; i < OUTBOX_CAP; i++) {
      note_migrated(box, i, migrate_record(&box->records[i], &old->records[i]), &newest);
    }
    return 1;
  }
  return 0;
}

enqueue_result_t outbox_enqueue(outbox_t *box, const packet_t *measurement,
                                const packet_t *device_info, uint32_t weight_grams,
                                char event_id[EVENT_ID_LEN]) {
  uint8_t digest[32];
  int     i;
  int     free_slot      = -1;
  int     delivered_slot = -1;

  if (!box || !event_id || weight_grams == 0 || !packet_ok(measurement) ||
      !packet_ok(device_info)) {
    return ENQUEUE_FAIL;
  }
  sha256(measurement->payload, measurement->length, digest);
  for (i = 0; i < OUTBOX_CAP; i++) {
    if (!box->records[i].occupied) {
      if (free_slot < 0) {
        free_slot = i;
      }
      continue;
    }
    if (hash_equal(box->records[i].payload_hash, digest)) {
      outbox_record_t *rec = &box->records[i];

      memcpy(event_id, rec->event_id, EVENT_ID_LEN);
      if (packets_empty(rec)) {
        copy_packet(&rec->device_info, device_info);
        copy_packet(&rec->measurement, measurement);
        rec->state = OUTBOX_QUEUED;
        return ENQUEUE_ENRICHED;
      }
      return ENQUEUE_DUP;
    }
    if (box->records[i].state == OUTBOX_DELIVERED && delivered_slot < 0) {
      delivered_slot = i;
    }
  }
  if (free_slot < 0) {
    free_slot = delivered_slot;
  }
  if (free_slot < 0) {
    return ENQUEUE_FULL;
  }
  {
    static const char hex[]        = "0123456789abcdef";
    outbox_record_t  *rec          = &box->records[free_slot];
    int               was_occupied = rec->occupied;

    memset(rec, 0, sizeof(*rec));
    rec->occupied     = 1;
    rec->state        = OUTBOX_QUEUED;
    rec->weight_grams = weight_grams;
    memcpy(rec->payload_hash, digest, 32);
    copy_packet(&rec->device_info, device_info);
    copy_packet(&rec->measurement, measurement);
    for (i = 0; i < 32; i++) {
      rec->event_id[i * 2]     = hex[digest[i] >> 4];
      rec->event_id[i * 2 + 1] = hex[digest[i] & 15];
    }
    rec->event_id[64] = 0;
    memcpy(event_id, rec->event_id, EVENT_ID_LEN);
    if (!was_occupied) {
      box->count++;
    }
    box->latest = free_slot;
  }
  return ENQUEUE_NEW;
}

int outbox_find_sendable(const outbox_t *box, int *index) {
  int i;
  for (i = 0; i < OUTBOX_CAP; i++) {
    if (box->records[i].occupied && box->records[i].state == OUTBOX_QUEUED) {
      *index = i;
      return 1;
    }
  }
  return 0;
}

int outbox_accept_http(outbox_t *box, const outbox_record_t *sent) {
  int i;

  if (!box || !sent) {
    return 0;
  }
  for (i = 0; i < OUTBOX_CAP; i++) {
    if (!box->records[i].occupied) {
      continue;
    }
    if (strcmp(box->records[i].event_id, sent->event_id) != 0) {
      continue;
    }
    /* A weight-only POST may finish after this reading gained raw packets.
     * Its ACK covers only what was sent, not the newly queued enrichment. */
    if (packets_empty(&box->records[i]) != packets_empty(sent)) {
      return 0;
    }
    if (box->records[i].state == OUTBOX_QUEUED) {
      box->records[i].state = OUTBOX_DELIVERED;
    }
    return 1;
  }
  return 0;
}

int outbox_queued_count(const outbox_t *box) {
  int i;
  int n = 0;
  for (i = 0; i < OUTBOX_CAP; i++) {
    if (box->records[i].occupied && box->records[i].state == OUTBOX_QUEUED) {
      n++;
    }
  }
  return n;
}

const outbox_record_t *outbox_latest(const outbox_t *box) {
  return box->latest >= 0 ? &box->records[box->latest] : NULL;
}
