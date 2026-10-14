import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from morphoscan import replay
from morphoscan_protocol import (
  FrameAssembler,
  Packet,
  acknowledge,
  decode_capabilities,
  decode_packet,
  encode_frames,
)

INFO_FRAMES = (
  bytes.fromhex("00001e00aab37116206425010a2500000000003d"),
  bytes.fromhex("00001e0100000000000000000000000000000020"),
)
INFO_PAYLOAD = bytes.fromhex(
  "aab37116206425010a250000000000000000000000000000000000000000"
)


class ProtocolTests(unittest.TestCase):
  def test_retransmissions_and_out_of_order_fragments_preserve_packet(self):
    assembler = FrameAssembler()
    self.assertIsNone(assembler.add(INFO_FRAMES[1]))
    self.assertIsNone(assembler.add(INFO_FRAMES[1]))
    packet = assembler.add(INFO_FRAMES[0])
    self.assertEqual(packet, Packet(INFO_PAYLOAD, 0, 1))
    decoded = decode_packet(packet)
    self.assertEqual(decoded["type"], "device_info")
    self.assertNotIn("weight_kg", decoded)
    self.assertEqual(decoded["capabilities"]["electrodes"], 8)
    self.assertEqual(decoded["capabilities"]["frequency_count"], 2)
    self.assertEqual(decoded["capabilities"]["impedances_per_frequency"], 5)
    self.assertEqual(acknowledge(packet, 0), bytes.fromhex("00000300b0000030"))

  def test_corruption_discards_incomplete_message_before_retransmission(self):
    assembler = FrameAssembler()
    self.assertIsNone(assembler.add(INFO_FRAMES[0]))
    damaged = bytearray(INFO_FRAMES[1])
    damaged[4] ^= 1
    with self.assertRaises(ValueError):
      assembler.add(bytes(damaged))
    self.assertIsNone(assembler.add(INFO_FRAMES[1]))
    self.assertEqual(assembler.add(INFO_FRAMES[0]).payload, INFO_PAYLOAD)

  def test_new_sequence_cannot_complete_an_older_packet(self):
    assembler = FrameAssembler()
    assembler.add(INFO_FRAMES[0])
    new_tail = bytes([1]) + INFO_FRAMES[1][1:]
    self.assertIsNone(assembler.add(new_tail))
    new_head = bytes([1]) + INFO_FRAMES[0][1:]
    self.assertEqual(assembler.add(new_head), Packet(INFO_PAYLOAD, 1, 1))

  def test_final_measurement_preserves_both_frequencies(self):
    # Synthetic A3: 75000 grams, algorithm 37, no HR, ten impedance words.
    payload = bytes.fromhex("a3250124f80003e807d00bb80fa0138817701b581f4023282710")
    capabilities = decode_capabilities(INFO_PAYLOAD)
    decoded = decode_packet(Packet(payload, 7, 1), capabilities)
    self.assertEqual(decoded["type"], "measurement")
    self.assertEqual(decoded["weight_g"], 75000)
    self.assertEqual(decoded["weight_kg"], 75)
    self.assertEqual(decoded["algorithm"], 37)
    self.assertEqual(
      decoded["impedance_values"], [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
    )
    self.assertNotIn("body_fat", decoded)
    with self.assertRaises(ValueError):
      decode_packet(Packet(payload[:-1], 7, 1), capabilities)
    with self.assertRaises(ValueError):
      decode_packet(Packet(payload, 7, 1))

  def test_padded_final_fragment_does_not_extend_measurement_payload(self):
    # Synthetic A7 with the same 38-byte layout as the physical scale's result.
    payload = bytes.fromhex(
      "a712345678250124f8000a03e807d00bb80fa0138817701b581f4023282710ffffffff000000"
    )
    frames = encode_frames(payload, 1, 1)
    padded = frames[-1][:-1] + b"padding"
    frames[-1] = padded + bytes([0x20 | (sum(padded[4:]) & 31)])
    assembler = FrameAssembler()
    for frame in frames:
      packet = assembler.add(frame)
    self.assertEqual(packet.payload, payload)
    decoded = decode_packet(packet, decode_capabilities(INFO_PAYLOAD))
    self.assertEqual(decoded["type"], "measurement")
    self.assertEqual(decoded["weight_kg"], 75)
    self.assertEqual(decoded["device_time"], 0x12345678)
    self.assertEqual(decoded["extra_hex"], "0000")

  def test_replay_preserves_early_weight_and_ignores_derived_rows(self):
    early_frame = encode_frames(bytes.fromhex("a201250124f800"), 0, 1)[0]
    rows = [
      {
        "characteristic": "0000ffb2-0000-1000-8000-00805f9b34fb",
        "hex": early_frame.hex(),
      },
      {
        "characteristic": "0000ffb3-0000-1000-8000-00805f9b34fb",
        "hex": INFO_FRAMES[0].hex(),
      },
      {
        "characteristic": "0000ffb3-0000-1000-8000-00805f9b34fb",
        "event": "packet",
        "decoded": {},
      },
      {
        "characteristic": "0000ffb3-0000-1000-8000-00805f9b34fb",
        "hex": INFO_FRAMES[1].hex(),
      },
    ]
    output = io.StringIO()
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "capture.jsonl"
      path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
      with redirect_stdout(output):
        replay(path)
    decoded = [json.loads(line) for line in output.getvalue().splitlines()]
    self.assertEqual(
      [(row["line"], row["type"]) for row in decoded],
      [(4, "device_info"), (1, "streaming")],
    )
    self.assertEqual(decoded[1]["weight_kg"], 75)


if __name__ == "__main__":
  unittest.main()
