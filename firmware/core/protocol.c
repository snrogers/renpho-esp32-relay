#include "protocol.h"

#include "sha256.h"

#include <string.h>

uint16_t bluetooth_uuid128_to_u16(const uint8_t uuid[16]) {
  static const uint8_t base[12] = {
      0xfb, 0x34, 0x9b, 0x5f, 0x80, 0x00, 0x00, 0x80, 0x00, 0x10, 0x00, 0x00};
  if (memcmp(uuid, base, sizeof(base)) != 0 || uuid[14] != 0 || uuid[15] != 0) {
    return 0;
  }
  return (uint16_t)uuid[12] | ((uint16_t)uuid[13] << 8);
}

void frame_assembler_init(frame_assembler_t *as) {
  memset(as, 0, sizeof(*as));
}

static void assembler_clear(frame_assembler_t *as) {
  memset(as->present, 0, sizeof(as->present));
  as->filled         = 0;
  as->stored         = 0;
  as->have_identity  = 0;
}

int frame_assembler_add(frame_assembler_t *as, const uint8_t *frame, size_t length,
                        packet_t *out) {
  uint8_t  sequence;
  uint16_t size;
  uint8_t  index;
  uint8_t  unit;
  const uint8_t *chunk;
  size_t   chunk_len;
  uint8_t  sum;
  size_t   i;
  uint16_t count;
  uint16_t expected;

  if (length < 6 || length > FRAME_MAX) {
    assembler_clear(as);
    return -1;
  }
  sequence = frame[0];
  size     = (uint16_t)((frame[1] << 8) | frame[2]);
  index    = frame[3];
  chunk    = frame + 4;
  chunk_len = length - 5;
  unit     = frame[length - 1] >> 5;
  sum      = 0;
  for (i = 0; i < chunk_len; i++) {
    sum = (uint8_t)(sum + chunk[i]);
  }
  if ((sum & 31) != (frame[length - 1] & 31)) {
    assembler_clear(as);
    return -1;
  }
  if (size == 0 || size > PAYLOAD_MAX || chunk_len > size) {
    assembler_clear(as);
    return -1;
  }
  if (!as->have_identity || as->sequence != sequence || as->size != size ||
      as->unit != unit) {
    memset(as->present, 0, sizeof(as->present));
    as->filled        = 0;
    as->stored        = 0;
    as->sequence      = sequence;
    as->size          = size;
    as->unit          = unit;
    as->have_identity = 1;
  }
  if (as->present[index]) {
    if (as->chunk_len[index] != chunk_len ||
        memcmp(as->chunks + as->chunk_offset[index], chunk, chunk_len) != 0) {
      assembler_clear(as);
      return -1;
    }
  } else {
    if (as->stored + chunk_len > sizeof(as->chunks)) {
      assembler_clear(as);
      return -1;
    }
    as->chunk_offset[index] = as->stored;
    memcpy(as->chunks + as->stored, chunk, chunk_len);
    as->stored = (uint16_t)(as->stored + chunk_len);
    as->chunk_len[index] = (uint16_t)chunk_len;
    as->present[index]   = 1;
    as->filled++;
  }
  if (!as->present[0]) {
    return 0;
  }
  as->capacity = as->chunk_len[0];
  if (as->capacity == 0) {
    assembler_clear(as);
    return -1;
  }
  count = (uint16_t)((size + as->capacity - 1) / as->capacity);
  if (count > 256) {
    assembler_clear(as);
    return -1;
  }
  for (i = 0; i < FRAGMENT_MAX; i++) {
    if (!as->present[i]) {
      continue;
    }
    if (i >= count) {
      assembler_clear(as);
      return -1;
    }
    expected = (uint16_t)((size - i * as->capacity) < as->capacity
                              ? (size - i * as->capacity)
                              : as->capacity);
    if (as->chunk_len[i] != expected && as->chunk_len[i] != as->capacity) {
      assembler_clear(as);
      return -1;
    }
  }
  if (as->filled != count) {
    return 0;
  }
  {
    uint16_t written = 0;
    for (i = 0; i < count; i++) {
      uint16_t take   = as->chunk_len[i];
      uint16_t remain = (uint16_t)(size - written);
      if (take > remain) {
        take = remain;
      }
      if (written + take > PAYLOAD_MAX) {
        assembler_clear(as);
        return -1;
      }
      memcpy(out->payload + written, as->chunks + as->chunk_offset[i], take);
      written = (uint16_t)(written + take);
    }
    if (written != size) {
      assembler_clear(as);
      return -1;
    }
    out->length   = size;
    out->sequence = sequence;
    out->unit     = unit;
  }
  assembler_clear(as);
  return 1;
}

int encode_frames(const uint8_t *payload, size_t length, uint8_t sequence, uint8_t unit,
                  int mtu, uint8_t out[][FRAME_MAX], int *out_lens, int max_frames) {
  int      capacity;
  int      frames = 0;
  size_t   offset = 0;
  uint8_t  index  = 0;

  if (!payload || length == 0 || length > 65535 || unit > 7) {
    return -1;
  }
  if (mtu < 6 || mtu > 512) {
    return -1;
  }
  capacity = mtu - 5;
  if ((int)((length + (size_t)capacity - 1) / (size_t)capacity) > 256) {
    return -1;
  }
  while (offset < length) {
    size_t   chunk_len = length - offset;
    uint8_t  sum       = 0;
    size_t   i;
    if ((int)chunk_len > capacity) {
      chunk_len = (size_t)capacity;
    }
    if (frames >= max_frames) {
      return -1;
    }
    out[frames][0] = sequence;
    out[frames][1] = (uint8_t)(length >> 8);
    out[frames][2] = (uint8_t)length;
    out[frames][3] = index;
    memcpy(out[frames] + 4, payload + offset, chunk_len);
    for (i = 0; i < chunk_len; i++) {
      sum = (uint8_t)(sum + payload[offset + i]);
    }
    out[frames][4 + chunk_len] = (uint8_t)((unit << 5) | (sum & 31));
    out_lens[frames]           = (int)(5 + chunk_len);
    frames++;
    index++;
    offset += chunk_len;
  }
  return frames;
}

int acknowledge(const packet_t *packet, uint8_t sequence, uint8_t out[FRAME_MAX]) {
  uint8_t payload[3];
  uint8_t frames[1][FRAME_MAX];
  int     lens[1];
  int     n;

  payload[0] = 0xB0;
  payload[1] = packet->sequence;
  payload[2] = 0;
  n          = encode_frames(payload, 3, sequence, packet->unit, 20, frames, lens, 1);
  if (n != 1) {
    return -1;
  }
  memcpy(out, frames[0], (size_t)lens[0]);
  return lens[0];
}

int decode_capabilities(const uint8_t *payload, size_t length, capabilities_t *caps) {
  int      extended;
  size_t   minimum;
  uint32_t flags;
  int      impedance_bit;

  memset(caps, 0, sizeof(*caps));
  if (!payload || (payload[0] != 0xA1 && payload[0] != 0xAA)) {
    return -1;
  }
  extended = payload[0] == 0xAA;
  minimum  = extended ? 20 : 10;
  if (length < minimum) {
    return -1;
  }
  flags = ((uint32_t)payload[1] << 24) | ((uint32_t)payload[2] << 16) |
          ((uint32_t)payload[3] << 8) | payload[4];
  caps->electrodes        = (flags & (1u << 24)) ? 8 : 4;
  caps->frequency_count   = (int)(((flags >> 25) & 7) + 1);
  caps->impedance_precision = (int)((flags >> 28) & 1);
  caps->kg_division       = (int)(flags & 7);
  caps->lb_division       = (int)((flags >> 3) & 7);
  impedance_bit           = (int)((flags >> 29) & 1);
  caps->impedances_per_frequency =
      caps->electrodes == 8 ? 6 - impedance_bit : 1 + impedance_bit;
  caps->valid = 1;
  return 0;
}

static uint32_t be32(const uint8_t *p) {
  return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

int decode_packet(const packet_t *packet, const capabilities_t *caps, decoded_t *out) {
  const uint8_t *payload = packet->payload;
  size_t         length  = packet->length;
  uint8_t        command;
  size_t         offset = 1;
  uint32_t       packed;
  int            is_measure_cmd;

  memset(out, 0, sizeof(*out));
  if (length == 0 || length > PAYLOAD_MAX) {
    return -1;
  }
  command        = payload[0];
  out->command   = command;
  out->sequence  = packet->sequence;
  out->unit      = packet->unit;
  out->type      = PKT_UNKNOWN;
  if (command == 0xA1 || command == 0xAA) {
    capabilities_t tmp;
    if (decode_capabilities(payload, length, &tmp) != 0) {
      return -1;
    }
    out->type = PKT_DEVICE_INFO;
    return 0;
  }
  if (command == 0xA0) {
    if (length < 3) {
      return -1;
    }
    out->type = PKT_COMMAND_REPLY;
    return 0;
  }
  is_measure_cmd = command == 0xA2 || command == 0xA3 || command == 0xA4 ||
                   command == 0xA5 || command == 0xA7;
  if (!is_measure_cmd) {
    return 0;
  }
  if (caps == NULL || !caps->valid) {
    return -1;
  }
  if (command == 0xA2) {
    if (length < 7) {
      return -1;
    }
    offset += 1;
  } else if (command == 0xA4 || command == 0xA5 || command == 0xA7) {
    if (length < 10) {
      return -1;
    }
    out->device_time     = be32(payload + offset);
    out->has_device_time = 1;
    offset += 4;
  }
  if (length < offset + 5) {
    return -1;
  }
  packed          = be32(payload + offset);
  out->weight_g   = packed & 0x3FFFFu;
  out->has_weight = 1;
  offset += 5;
  if (command == 0xA2) {
    out->type = PKT_STREAMING;
  } else if (command == 0xA4 || command == 0xA5) {
    out->type = PKT_HISTORY;
  } else {
    out->type = PKT_MEASUREMENT;
  }
  if (command != 0xA2) {
    int count = caps->frequency_count * caps->impedances_per_frequency;
    if (command == 0xA5 || command == 0xA7) {
      if (length <= offset) {
        return -1;
      }
      count = payload[offset];
      offset += 1;
    }
    if (length < offset + (size_t)count * 2) {
      return -1;
    }
    offset += (size_t)count * 2;
    if (command == 0xA5 || command == 0xA7) {
      if (length < offset + 5) {
        return -1;
      }
    }
  }
  return 0;
}

void packet_decoder_init(packet_decoder_t *dec) {
  memset(dec, 0, sizeof(*dec));
}

int packet_decoder_feed(packet_decoder_t *dec, const packet_t *packet, decoded_t *out,
                        int *released) {
  decoded_t decoded;
  int       err;

  *released = 0;
  err       = decode_packet(packet, dec->caps.valid ? &dec->caps : NULL, &decoded);
  if (decoded.type == PKT_DEVICE_INFO) {
    decode_capabilities(packet->payload, packet->length, &dec->caps);
    dec->device_info.length = packet->length;
    dec->device_info.sequence = packet->sequence;
    dec->device_info.unit = packet->unit;
    memcpy(dec->device_info.payload, packet->payload, packet->length);
    *out      = decoded;
    *released = 1;
    return 0;
  }
  if (!dec->caps.valid) {
    if (dec->pending_count < PACKET_PENDING) {
      dec->pending[dec->pending_count++] = *packet;
    }
    return 0;
  }
  if (err != 0) {
    return err;
  }
  *out      = decoded;
  *released = 1;
  return 0;
}

int packet_decoder_flush(packet_decoder_t *dec, packet_t *packet, decoded_t *out) {
  while (dec->pending_count > 0) {
    packet_t pending = dec->pending[0];
    int      i;
    for (i = 1; i < dec->pending_count; i++) {
      dec->pending[i - 1] = dec->pending[i];
    }
    dec->pending_count--;
    if (decode_packet(&pending, &dec->caps, out) == 0) {
      *packet = pending;
      return 1;
    }
  }
  return 0;
}

void event_id_from_payload(const uint8_t *payload, size_t length, char event_id[65]) {
  static const char hex[] = "0123456789abcdef";
  uint8_t           digest[32];
  int               i;

  sha256(payload, length, digest);
  for (i = 0; i < 32; i++) {
    event_id[i * 2]     = hex[digest[i] >> 4];
    event_id[i * 2 + 1] = hex[digest[i] & 15];
  }
  event_id[64] = 0;
}

int scale_name_matches(const uint8_t *name, size_t length) {
  static const char want[] = "R-MSC01";
  return name && length == sizeof(want) - 1 && memcmp(name, want, length) == 0;
}
