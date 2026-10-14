/** Pure progress arithmetic and text for the installer. No DOM access, so Node tests can import it. */

const MB = 1024 * 1024;

export function formatBytes(bytes) {
  if (bytes >= MB) return `${(bytes / MB).toFixed(1)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

export function formatDuration(ms) {
  const seconds = Math.max(1, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds} s`;
  return `${Math.round(seconds / 60)} min`;
}

/**
 * Overall fraction of a multi-file flash write.
 * esptool-js reports `written` and `total` in compressed bytes of file `index`,
 * so each file counts by its uncompressed size and its own compressed fraction.
 */
export function writeFraction(sizes, index, written, total) {
  const all = sizes.reduce((sum, size) => sum + size, 0);
  if (all === 0) return 0;
  const before = sizes.slice(0, index).reduce((sum, size) => sum + size, 0);
  const current = total > 0 ? Math.min(written / total, 1) : 0;
  return Math.min((before + current * (sizes[index] ?? 0)) / all, 1);
}

/** One line such as "42% · 6.7 of 16.0 MB · about 2 min left". */
export function describeProgress({ fraction, totalBytes, elapsedMs }) {
  const clamped = Math.min(Math.max(fraction, 0), 1);
  const parts = [`${Math.floor(clamped * 100)}%`];
  if (totalBytes > 0) parts.push(`${formatBytes(clamped * totalBytes)} of ${formatBytes(totalBytes)}`);
  // Early rates are noisy: give a time only after a few seconds and a few percent.
  if (clamped >= 0.03 && clamped < 1 && elapsedMs >= 3000) {
    parts.push(`about ${formatDuration((elapsedMs / clamped) * (1 - clamped))} left`);
  }
  return parts.join(" · ");
}
