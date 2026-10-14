#ifndef RELAY_PROTOCOL_H
#define RELAY_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

enum {
  FRAME_MAX        = 512,
  PAYLOAD_MAX      = 512,
  FRAGMENT_MAX     = 256,
  PACKET_PENDING   = 8
};

typedef enum {
  PKT_UNKNOWN = 0,
  PKT_DEVICE_INFO,
  PKT_COMMAND_REPLY,
  PKT_STREAMING,
  PKT_HISTORY,
  PKT_MEASUREMENT
} packet_type_t;

typedef struct {
  uint8_t  payload[PAYLOAD_MAX];
  uint16_t length;
  uint8_t  sequence;
  uint8_t  unit;
} packet_t;

typedef struct {
  uint8_t  chunks[PAYLOAD_MAX + FRAME_MAX];
  uint16_t chunk_offset[FRAGMENT_MAX];
  uint16_t chunk_len[FRAGMENT_MAX];
  uint8_t  present[FRAGMENT_MAX];
  uint16_t size;
  uint8_t  sequence;
  uint8_t  unit;
  uint8_t  have_identity;
  uint16_t capacity;
  uint16_t filled;
  uint16_t stored;
} frame_assembler_t;

typedef struct {
  int electrodes;
  int frequency_count;
  int impedances_per_frequency;
  int impedance_precision;
  int kg_division;
  int lb_division;
  int valid;
} capabilities_t;

typedef struct {
  packet_type_t type;
  uint8_t       command;
  uint8_t       sequence;
  uint8_t       unit;
  uint32_t      weight_g;
  uint32_t      device_time;
  int           has_device_time;
  int           has_weight;
} decoded_t;

typedef struct {
  packet_t       device_info;
  packet_t       pending[PACKET_PENDING];
  int            pending_count;
  capabilities_t caps;
} packet_decoder_t;

/* Shorten a little-endian Bluetooth-base UUID; unrelated UUIDs return zero. */
uint16_t bluetooth_uuid128_to_u16(const uint8_t uuid[16]);

void frame_assembler_init(frame_assembler_t *as);
int  frame_assembler_add(frame_assembler_t *as, const uint8_t *frame, size_t length,
                         packet_t *out);

int  encode_frames(const uint8_t *payload, size_t length, uint8_t sequence, uint8_t unit,
                   int mtu, uint8_t out[][FRAME_MAX], int *out_lens, int max_frames);
int  acknowledge(const packet_t *packet, uint8_t sequence, uint8_t out[FRAME_MAX]);

int  decode_capabilities(const uint8_t *payload, size_t length, capabilities_t *caps);
int  decode_packet(const packet_t *packet, const capabilities_t *caps, decoded_t *out);

void packet_decoder_init(packet_decoder_t *dec);
int  packet_decoder_feed(packet_decoder_t *dec, const packet_t *packet, decoded_t *out,
                         int *released);
int  packet_decoder_flush(packet_decoder_t *dec, packet_t *packet, decoded_t *out);


void event_id_from_payload(const uint8_t *payload, size_t length, char event_id[65]);

/* The R-MSC01 advertises this local name; auto-pairing connects only to it. */
int  scale_name_matches(const uint8_t *name, size_t length);

#endif
