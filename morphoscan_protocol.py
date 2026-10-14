"""ICOMON General V2 transport recovered from MorphoScan Android 1.9.8.

Wire evidence: libICBleProtocol.so, ICBleScaleGeneralProtocolV2; Java
ICWeightScaleV3Worker. This module never synthesizes body-composition estimates.
"""

import struct
from collections import deque
from dataclasses import dataclass

MEASUREMENT_COMMANDS = (0xA2, 0xA3, 0xA4, 0xA5, 0xA7)


@dataclass(frozen=True)
class Packet:
  payload: bytes
  sequence: int
  unit: int


class FrameAssembler:
  """Reassemble one characteristic's packets; never mix notification streams."""

  def __init__(self):
    self._chunks = {}
    self._identity = None

  def add(self, frame: bytes) -> Packet | None:
    if len(frame) < 6:
      self._chunks.clear()
      raise ValueError("Frame is shorter than its header, payload and checksum")
    sequence, size, index = struct.unpack_from(">BHB", frame)
    chunk = frame[4:-1]
    unit = frame[-1] >> 5
    if sum(chunk) & 31 != frame[-1] & 31:
      self._chunks.clear()
      raise ValueError("Frame checksum mismatch")
    if not size or len(chunk) > size:
      self._chunks.clear()
      raise ValueError("Invalid declared packet size")
    identity = (sequence, size, unit)
    if identity != self._identity:
      self._chunks.clear()
      self._identity = identity
    previous = self._chunks.get(index)
    if previous is not None and previous != chunk:
      self._chunks.clear()
      raise ValueError("Conflicting copies of a fragment")
    self._chunks[index] = chunk
    if 0 not in self._chunks:
      return None
    capacity = len(self._chunks[0])
    count = (size + capacity - 1) // capacity
    if count > 256:
      self._chunks.clear()
      raise ValueError("Fragment index exceeds declared packet size")
    for number, data in self._chunks.items():
      if number >= count:
        self._chunks.clear()
        raise ValueError("Fragment index exceeds declared packet size")
      expected = min(capacity, size - number * capacity)
      # Firmware pads the final fragment to capacity; the checksum includes padding.
      if len(data) not in (expected, capacity):
        self._chunks.clear()
        raise ValueError("Fragment length disagrees with packet header")
    if len(self._chunks) != count:
      return None
    payload = b"".join(self._chunks[number] for number in range(count))[:size]
    self._chunks.clear()
    return Packet(payload, sequence, unit)


class PacketDecoder:
  """Wait for capabilities without losing early packets or their source tags."""

  def __init__(self):
    self._capabilities = None
    self._pending = deque()

  def decode(self, packet: Packet, source):
    if (
      self._capabilities is None
      and packet.payload
      and packet.payload[0] in MEASUREMENT_COMMANDS
    ):
      self._pending.append((packet, source))
      return
    decoded = decode_packet(packet, self._capabilities)
    if decoded["type"] == "device_info":
      self._capabilities = decoded["capabilities"]
    yield source, packet, decoded
    if self._capabilities is not None:
      while self._pending:
        pending, pending_source = self._pending.popleft()
        yield pending_source, pending, decode_packet(pending, self._capabilities)


def encode_frames(
  payload: bytes, sequence: int, unit: int, mtu: int = 20
) -> list[bytes]:
  if (
    not payload
    or len(payload) > 65535
    or not 0 <= sequence <= 255
    or not 0 <= unit <= 7
  ):
    raise ValueError("Invalid packet fields")
  if not 6 <= mtu <= 512:
    raise ValueError("Invalid ATT payload capacity")
  capacity = mtu - 5
  if (len(payload) + capacity - 1) // capacity > 256:
    raise ValueError("Packet exceeds fragment index range")
  return [
    struct.pack(">BHB", sequence, len(payload), index)
    + chunk
    + bytes([(unit << 5) | (sum(chunk) & 31)])
    for index, offset in enumerate(range(0, len(payload), capacity))
    for chunk in (payload[offset : offset + capacity],)
  ]


def acknowledge(packet: Packet, sequence: int) -> bytes:
  """B0 acknowledges receipt only; callers decide which messages may be ACKed."""
  return encode_frames(bytes([0xB0, packet.sequence, 0]), sequence, packet.unit)[0]


def decode_capabilities(payload: bytes) -> dict:
  extended = payload[:1] == b"\xaa"
  minimum = 20 if extended else 10
  if not payload or payload[0] not in (0xA1, 0xAA) or len(payload) < minimum:
    raise ValueError("Truncated or unsupported device-information packet")
  flags = int.from_bytes(payload[1:5], "big")
  fields = {
    "battery_type": (flags >> 18) & 3,
    "calculation_type": (flags >> 11) & 1,
    "electrodes": 8 if flags & (1 << 24) else 4,
    "frequency_count": ((flags >> 25) & 7) + 1,
    "impedance_precision": (flags >> 28) & 1,
    "kg_division": flags & 7,
    "lb_division": (flags >> 3) & 7,
    "pole_support": bool(flags & (1 << 30)),
    "protocol_version2": flags >> 31,
    "supports_balance": bool(flags & (1 << 8)),
    "supports_gravity": bool(flags & (1 << 7)),
    "supports_heart_rate": bool(flags & (1 << 6)),
    "supports_history": bool(flags & (1 << 10)),
    "supports_profiles": bool(flags & (1 << 12)),
    "user_capacity": (flags >> 13) & 31,
  }
  impedance_bit = (flags >> 29) & 1
  fields["impedances_per_frequency"] = (
    6 - impedance_bit if fields["electrodes"] == 8 else 1 + impedance_bit
  )
  offset = 9 if extended else 8
  fields.update(
    {
      "algorithm": payload[6],
      "algorithm2": payload[offset],
      "battery": payload[5],
      "enabled_measurements": payload[7],
      "impedance_property": payload[8] if extended else 0,
      "protocol_version": payload[offset + 1],
      "raw_flags": flags,
      "supported_units": [index for index in range(4) if flags & (1 << (20 + index))],
    }
  )
  return fields


def _float32(value: float) -> float:
  return struct.unpack("<f", struct.pack("<f", value))[0]


def _rounded_weight(value: float, division: int) -> float:
  # SDK gunit_general rounding includes a one-unit floating-point correction.
  if division > 4:
    return value
  multiplier = 1000 if division < 3 else 100
  scaled = _float32(value * multiplier)
  if int(_float32(scaled * 10)) % 10 >= 9:
    scaled = _float32(scaled + 1)
  integer = int(scaled)
  if division in (0, 3):
    rounded = (integer + 5) // 10
  elif division in (1, 4):
    if integer % 10 == 9:
      integer += 10
    rounded = integer // 10
    rounded += rounded & 1
  else:
    rounded = ((integer + 20) // 10) // 5 * 5
  return rounded / (100 if division < 3 else 10)


def decode_packet(packet: Packet, capabilities: dict | None = None) -> dict:
  payload = packet.payload
  if not payload:
    raise ValueError("Empty application packet")
  command = payload[0]
  result = {
    "command": f"{command:02x}",
    "sequence": packet.sequence,
    "unit": packet.unit,
  }
  if command in (0xA1, 0xAA):
    return result | {
      "capabilities": decode_capabilities(payload),
      "type": "device_info",
    }
  if command == 0xA0:
    if len(payload) < 3:
      raise ValueError("Truncated command reply")
    return result | {
      "reply_sequence": payload[1],
      "state": payload[2],
      "type": "command_reply",
    }
  if command not in MEASUREMENT_COMMANDS:
    return result | {"type": "unknown"}
  if capabilities is None:
    raise ValueError("Measurement arrived before device capabilities")
  offset = 1
  if command == 0xA2:
    if len(payload) < 7:
      raise ValueError("Truncated streaming measurement")
    result["state"] = payload[offset]
    offset += 1
  elif command in (0xA4, 0xA5, 0xA7):
    if len(payload) < 10:
      raise ValueError("Truncated timestamped measurement")
    result["device_time"] = int.from_bytes(payload[offset : offset + 4], "big")
    offset += 4
  if len(payload) < offset + 5:
    raise ValueError("Truncated weight and heart rate")
  packed_weight = int.from_bytes(payload[offset : offset + 4], "big")
  heart_rate = payload[offset + 4]
  offset += 5
  kg_division = ((packed_weight >> 18) & 7) or capabilities["kg_division"]
  lb_division = ((packed_weight >> 21) & 7) or capabilities["lb_division"]
  grams = packed_weight & 0x3FFFF
  kilograms = _rounded_weight(_float32(grams / 1000), kg_division)
  result.update(
    {
      "algorithm": packed_weight >> 24,
      "heart_rate": heart_rate,
      "kg_division": kg_division,
      "lb_division": lb_division,
      "type": "streaming"
      if command == 0xA2
      else "history"
      if command in (0xA4, 0xA5)
      else "measurement",
      "weight_g": grams,
      "weight_kg": kilograms,
    }
  )
  if command != 0xA2:
    count = capabilities["frequency_count"] * capabilities["impedances_per_frequency"]
    if command in (0xA5, 0xA7):
      if len(payload) <= offset:
        raise ValueError("Missing impedance count")
      count = payload[offset]
      offset += 1
    if len(payload) < offset + count * 2:
      raise ValueError("Truncated impedance measurements")
    raw = list(struct.unpack_from(f">{count}H", payload, offset))
    divisor = 10 if capabilities["impedance_precision"] == 1 else 1
    result["impedance_raw"] = raw
    result["impedance_values"] = [value / divisor for value in raw]
    result["impedance_property"] = capabilities["impedance_property"]
    offset += count * 2
    if command in (0xA5, 0xA7):
      if len(payload) < offset + 5:
        raise ValueError("Truncated identified measurement")
      result["user_id"] = int.from_bytes(payload[offset : offset + 4], "big")
      result["extension_flags"] = payload[offset + 4]
      offset += 5
  if offset < len(payload):
    result["extra_hex"] = payload[offset:].hex()
  return result
