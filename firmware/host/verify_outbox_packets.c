#include "outbox.h"

#include <stdio.h>
#include <string.h>

static int failures;

static void expect(int cond, const char *msg) {
  if (!cond) {
    printf("FAIL %s\n", msg);
    failures++;
  }
}

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
  legacy_record_t records[OUTBOX_CAP];
  int             count;
} legacy_outbox_t;

typedef struct {
  legacy_record_t head;
  packet_t        device_info;
  packet_t        measurement;
} obx2_record_t;

typedef struct {
  uint32_t      format;
  obx2_record_t records[OUTBOX_CAP];
  int           count;
} obx2_outbox_t;

static void fill_packet(packet_t *p, uint8_t tag, uint16_t length, uint8_t seq, uint8_t unit) {
  uint16_t i;

  memset(p, 0, sizeof(*p));
  p->length   = length;
  p->sequence = seq;
  p->unit     = unit;
  for (i = 0; i < length; i++) {
    p->payload[i] = (uint8_t)(tag + i);
  }
}

static void put_legacy(legacy_record_t *rec, const char *id, const char *at, uint32_t grams,
                       uint32_t unix, int dated, int delivered, const uint8_t hash[32]) {
  memset(rec, 0, sizeof(*rec));
  strncpy(rec->event_id, id, EVENT_ID_LEN - 1);
  strncpy(rec->measured_at, at, sizeof(rec->measured_at) - 1);
  rec->weight_grams = grams;
  rec->capture_unix = unix;
  memcpy(rec->payload_hash, hash, 32);
  rec->dated    = dated ? 1 : 0;
  rec->occupied = 1;
  rec->state    = delivered ? OUTBOX_DELIVERED : OUTBOX_QUEUED;
}

int verify_outbox_packets(void) {
  failures = 0;

  {
    legacy_outbox_t legacy;
    outbox_t        box;
    outbox_t        prior;
    uint8_t         h_q[32];
    uint8_t         h_d[32];
    uint8_t         h_u[32];
    int             i;

    memset(&legacy, 0, sizeof(legacy));
    memset(h_q, 0x11, 32);
    memset(h_d, 0x22, 32);
    memset(h_u, 0x33, 32);
    put_legacy(&legacy.records[0], "queued-id", "2026-01-02T03:04:05+00:00", 75000, 100, 1, 0, h_q);
    put_legacy(&legacy.records[3], "delivered-id", "2026-01-01T00:00:00+00:00", 70000, 50, 1, 1, h_d);
    put_legacy(&legacy.records[7], "undated-id", "", 1000, 0, 0, 0, h_u);
    legacy.count = 99;

    outbox_init(&box);
    prior = box;
    expect(outbox_restore(&box, &legacy, sizeof(legacy)), "legacy restore");
    expect(box.count == 3, "occupancy from records not lifetime count");
    expect(box.records[0].occupied && box.records[0].state == OUTBOX_QUEUED, "queued kept");
    expect(strcmp(box.records[0].event_id, "queued-id") == 0, "queued id");
    expect(box.records[0].weight_grams == 75000, "queued weight");
    expect(box.records[0].device_info.length == 0 && box.records[0].measurement.length == 0,
           "queued no invented packets");
    expect(box.records[3].occupied && box.records[3].state == OUTBOX_DELIVERED, "delivered kept");
    expect(strcmp(box.records[3].event_id, "delivered-id") == 0, "delivered id");
    expect(box.records[3].device_info.length == 0, "delivered no invented packets");
    expect(box.records[7].occupied && box.records[7].weight_grams == 1000, "undated kept");
    expect(outbox_queued_count(&box) == 2, "queued+undated");
    expect(outbox_latest(&box) == &box.records[0], "latest follows old capture order");
    {
      int idx;
      expect(outbox_find_sendable(&box, &idx) && idx == 0, "queued sendable");
      box.records[0].state = OUTBOX_DELIVERED;
      expect(outbox_find_sendable(&box, &idx) && idx == 7, "undated record now sendable");
    }
    for (i = 0; i < OUTBOX_CAP; i++) {
      if (i != 0 && i != 3 && i != 7) {
        expect(!box.records[i].occupied, "empty slots stay empty");
      }
    }

    outbox_init(&box);
    prior = box;
    expect(!outbox_restore(&box, &legacy, 16), "short blob rejected");
    expect(memcmp(&box, &prior, sizeof(box)) == 0, "reject leaves box");
    legacy.records[0].event_id[EVENT_ID_LEN - 1] = 1;
    memset(legacy.records[0].event_id, 'a', EVENT_ID_LEN);
    expect(!outbox_restore(&box, &legacy, sizeof(legacy)), "unterminated id rejected");
    expect(memcmp(&box, &prior, sizeof(box)) == 0, "corrupt legacy leaves box");
  }

  {
    outbox_t box;
    outbox_t reloaded;
    packet_t meas;
    packet_t info;
    packet_t info2;
    char     id[EVENT_ID_LEN];
    char     id2[EVENT_ID_LEN];
    uint8_t  blob[sizeof(outbox_t)];

    fill_packet(&meas, 0xa7, PAYLOAD_MAX, 3, 7);
    fill_packet(&info, 0x10, PAYLOAD_MAX, 1, 2);
    fill_packet(&info2, 0x99, 8, 9, 1);
    outbox_init(&box);
    expect(outbox_enqueue(&box, &meas, &info, 80000, id) ==
             ENQUEUE_NEW,
           "new full packets");
    expect(box.records[0].measurement.length == PAYLOAD_MAX, "meas length stored");
    expect(box.records[0].measurement.payload[PAYLOAD_MAX - 1] == (uint8_t)(0xa7 + PAYLOAD_MAX - 1),
           "trailing meas byte");
    expect(box.records[0].device_info.payload[0] == 0x10, "info byte");
    memcpy(blob, &box, sizeof(box));
    outbox_init(&reloaded);
    expect(outbox_restore(&reloaded, blob, sizeof(blob)), "current restore");
    expect(reloaded.count == 1, "reload occupancy");
    expect(
      memcmp(&reloaded.records[0].measurement, &box.records[0].measurement, sizeof(packet_t)) == 0,
      "reload measurement bytes");
    expect(
      memcmp(&reloaded.records[0].device_info, &box.records[0].device_info, sizeof(packet_t)) == 0,
      "reload device info bytes");
    expect(strcmp(reloaded.records[0].event_id, id) == 0, "reload event id");
    expect(outbox_enqueue(&reloaded, &meas, &info2, 1, id2) == ENQUEUE_DUP,
           "complete dup");
    expect(
      memcmp(&reloaded.records[0].device_info, &box.records[0].device_info, sizeof(packet_t)) == 0,
      "dup keeps original packets");
    expect(reloaded.records[0].weight_grams == 80000, "dup keeps weight");
    expect(reloaded.latest == 0, "reload keeps latest");
    expect(strcmp(id2, id) == 0, "dup returns original id");
  }

  {
    legacy_outbox_t legacy;
    outbox_t        box;
    packet_t        meas;
    packet_t        info;
    char            id[EVENT_ID_LEN];
    uint8_t         hash[32];
    int             queued;

    memset(&legacy, 0, sizeof(legacy));
    memset(hash, 0, 32);
    fill_packet(&meas, 0x50, 6, 4, 1);
    fill_packet(&info, 0x60, 4, 2, 0);
    {
      /* SHA256 of meas payload computed by enqueue; plant matching hash via first enqueue path
         after restore by copying hash from a throwaway box. */
      outbox_t tmp;
      char     tmpid[EVENT_ID_LEN];
      outbox_init(&tmp);
      outbox_enqueue(&tmp, &meas, &info, 12345, tmpid);
      memcpy(hash, tmp.records[0].payload_hash, 32);
      put_legacy(&legacy.records[2], tmpid, "2026-05-06T07:08:09+00:00", 12345, 777, 1, 1, hash);
      legacy.count = 1;
      outbox_init(&box);
      expect(outbox_restore(&box, &legacy, sizeof(legacy)), "legacy for enrich");
      expect(box.records[2].state == OUTBOX_DELIVERED, "was delivered");
      expect(box.count == 1, "pre-enrich occupancy");
      queued = outbox_queued_count(&box);
      expect(outbox_enqueue(&box, &meas, &info, 99999, id) == ENQUEUE_ENRICHED,
             "enrich requeues");
      expect(box.count == 1, "enrich does not increment occupancy");
      expect(outbox_queued_count(&box) == queued + 1, "enrich queued");
      expect(box.records[2].state == OUTBOX_QUEUED, "requeued");
      expect(strcmp(box.records[2].event_id, tmpid) == 0, "enrich keeps id");
      expect(strcmp(id, tmpid) == 0, "enrich returns id");
      expect(box.records[2].weight_grams == 12345, "enrich keeps weight");
      expect(box.latest == 2, "enrich keeps latest");
      expect(box.records[2].measurement.length == 6, "enrich meas");
      expect(box.records[2].device_info.length == 4, "enrich info");
      expect(outbox_enqueue(&box, &meas, &info, 1, id) == ENQUEUE_DUP,
             "second enrich is dup");
      expect(box.records[2].weight_grams == 12345, "dup after enrich keeps weight");

      legacy.records[2].state = OUTBOX_QUEUED;
      expect(outbox_restore(&box, &legacy, sizeof(legacy)), "queued legacy restore");
      outbox_record_t sent = box.records[2];
      expect(outbox_enqueue(&box, &meas, &info, 12345, id) == ENQUEUE_ENRICHED,
             "enrichment while weight-only POST is in flight");
      expect(!outbox_accept_http(&box, &sent),
             "old weight-only ACK must not discard unsent raw packets");
      expect(outbox_queued_count(&box) == 1, "enriched reading remains queued");
      sent = box.records[2];
      expect(outbox_accept_http(&box, &sent), "full packet upload accepted");
      expect(outbox_queued_count(&box) == 0, "raw capture dequeues after its own ACK");
    }
  }

  {
    outbox_t box;
    packet_t meas;
    packet_t info;
    char     id[EVENT_ID_LEN];
    int      i;

    outbox_init(&box);
    for (i = 0; i < OUTBOX_CAP; i++) {
      fill_packet(&meas, (uint8_t)i, 3, 1, 0);
      fill_packet(&info, 0x80, 2, 1, 0);
      expect(outbox_enqueue(&box, &meas, &info, 1000 + (uint32_t)i, id) == ENQUEUE_NEW,
             "fill");
    }
    expect(box.count == OUTBOX_CAP, "full occupancy");
    fill_packet(&meas, 0xfe, 3, 1, 0);
    expect(outbox_enqueue(&box, &meas, &info, 1, id) ==
             ENQUEUE_FULL,
           "full no delivered");
    expect(box.count == OUTBOX_CAP, "full count unchanged");
    expect(outbox_accept_http(&box, &box.records[0]), "ack one");
    fill_packet(&meas, 0xfe, 3, 1, 0);
    expect(outbox_enqueue(&box, &meas, &info, 42, id) ==
             ENQUEUE_NEW,
           "reuse delivered slot");
    expect(box.count == OUTBOX_CAP, "reuse does not increment occupancy");
    expect(box.records[0].weight_grams == 42, "reused slot holds new");
    expect(box.records[0].state == OUTBOX_QUEUED, "reused queued");
  }

  {
    static obx2_outbox_t old;
    outbox_t             box;
    outbox_t             prior;
    uint8_t              h_a[32];
    uint8_t              h_b[32];

    memset(&old, 0, sizeof(old));
    memset(h_a, 0x44, 32);
    memset(h_b, 0x55, 32);
    old.format = OUTBOX_OBX2_FORMAT;
    put_legacy(&old.records[1].head, "older-id", "2026-01-01T00:00:00+00:00", 70000, 50, 1, 1, h_a);
    fill_packet(&old.records[1].device_info, 0x10, 4, 1, 0);
    fill_packet(&old.records[1].measurement, 0xa7, 6, 2, 1);
    put_legacy(&old.records[4].head, "newer-id", "2026-01-02T00:00:00+00:00", 71000, 90, 1, 0, h_b);
    fill_packet(&old.records[4].device_info, 0x20, 4, 3, 0);
    fill_packet(&old.records[4].measurement, 0xa7, 8, 4, 1);
    old.count = 2;

    outbox_init(&box);
    expect(outbox_restore(&box, &old, sizeof(old)), "OBX2 restore");
    expect(box.format == OUTBOX_FORMAT, "OBX2 becomes OBX3");
    expect(box.count == 2, "OBX2 occupancy");
    expect(strcmp(box.records[4].event_id, "newer-id") == 0, "OBX2 id kept");
    expect(box.records[4].state == OUTBOX_QUEUED, "OBX2 queued state kept");
    expect(box.records[1].state == OUTBOX_DELIVERED, "OBX2 delivered state kept");
    expect(memcmp(box.records[4].payload_hash, h_b, 32) == 0, "OBX2 hash kept");
    expect(memcmp(&box.records[4].measurement, &old.records[4].measurement, sizeof(packet_t)) == 0,
           "OBX2 measurement kept");
    expect(memcmp(&box.records[1].device_info, &old.records[1].device_info, sizeof(packet_t)) == 0,
           "OBX2 device info kept");
    expect(outbox_latest(&box) == &box.records[4], "OBX2 latest by old capture order");

    old.count = 3;
    outbox_init(&box);
    prior = box;
    expect(!outbox_restore(&box, &old, sizeof(old)), "OBX2 count mismatch rejected");
    expect(memcmp(&box, &prior, sizeof(box)) == 0, "bad OBX2 leaves box");
    old.count  = 2;
    old.format = OUTBOX_FORMAT;
    expect(!outbox_restore(&box, &old, sizeof(old)), "OBX2 size with wrong magic rejected");
  }

  {
    outbox_t box;
    outbox_t prior;
    uint8_t  garbage[sizeof(outbox_t)];

    outbox_init(&box);
    memset(garbage, 0xff, sizeof(garbage));
    prior = box;
    expect(!outbox_restore(&box, garbage, sizeof(garbage)), "junk current rejected");
    expect(memcmp(&box, &prior, sizeof(box)) == 0, "junk leaves data");
    expect(!outbox_restore(&box, garbage, OUTBOX_LEGACY_SIZE), "junk legacy size rejected");
    expect(memcmp(&box, &prior, sizeof(box)) == 0, "junk legacy leaves data");
    {
      static outbox_t bad;
      outbox_init(&bad);
      bad.latest = 3;
      expect(!outbox_restore(&box, &bad, sizeof(bad)), "latest on empty slot rejected");
      bad.latest = OUTBOX_CAP;
      expect(!outbox_restore(&box, &bad, sizeof(bad)), "latest out of range rejected");
      expect(memcmp(&box, &prior, sizeof(box)) == 0, "bad latest leaves data");
    }
  }

  return failures;
}
