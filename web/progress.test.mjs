import assert from "node:assert/strict";
import { test } from "node:test";

import { describeProgress, formatBytes, formatDuration, writeFraction } from "./progress.js";

test("formats sizes and durations", () => {
  assert.equal(formatBytes(3072), "3 KB");
  assert.equal(formatBytes(16 * 1024 * 1024), "16.0 MB");
  assert.equal(formatDuration(400), "1 s");
  assert.equal(formatDuration(42_000), "42 s");
  assert.equal(formatDuration(150_000), "3 min");
});

test("write progress uses each file's compressed fraction and uncompressed weight", () => {
  const sizes = [21056, 3072, 1202592];
  const all = sizes[0] + sizes[1] + sizes[2];
  assert.equal(writeFraction(sizes, 0, 0, 9000), 0);
  // Compressed totals are smaller than the files. A finished file still counts fully.
  assert.equal(writeFraction(sizes, 0, 9000, 9000), sizes[0] / all);
  assert.equal(writeFraction(sizes, 2, 350_000, 700_000), (sizes[0] + sizes[1] + sizes[2] / 2) / all);
  assert.equal(writeFraction(sizes, 2, 700_000, 700_000), 1);
});

test("write progress stays within 0 and 1 for odd input", () => {
  assert.equal(writeFraction([], 0, 1, 1), 0);
  assert.equal(writeFraction([100], 0, 5, 0), 0);
  assert.equal(writeFraction([100], 0, 150, 100), 1);
});

test("describes progress with bytes and, once stable, the time left", () => {
  const total = 16 * 1024 * 1024;
  assert.equal(describeProgress({ fraction: 0.01, totalBytes: total, elapsedMs: 5000 }), "1% · 164 KB of 16.0 MB");
  assert.equal(describeProgress({ fraction: 0.5, totalBytes: total, elapsedMs: 1000 }), "50% · 8.0 MB of 16.0 MB");
  assert.equal(
    describeProgress({ fraction: 0.25, totalBytes: total, elapsedMs: 60_000 }),
    "25% · 4.0 MB of 16.0 MB · about 3 min left",
  );
  assert.equal(describeProgress({ fraction: 1, totalBytes: total, elapsedMs: 240_000 }), "100% · 16.0 MB of 16.0 MB");
  assert.equal(describeProgress({ fraction: 0.5, totalBytes: 0, elapsedMs: 10_000 }), "50% · about 10 s left");
  assert.equal(describeProgress({ fraction: 1.7, totalBytes: 0, elapsedMs: 0 }), "100%");
});
