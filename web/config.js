// Relay configuration checks. These mirror validate_config in firmware/flash.py.

const LIMITS = {
  deviceId:     128,
  receiverUrl:  256,
  scaleAddress: 17,
  wifiPassword: 64,
  wifiSsid:     32,
};
const DEVICE_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const MAC = /^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$/;

const bytes = (text) => new TextEncoder().encode(text).length;

/** Return { config } with exactly the fields the firmware takes, or { error }. */
export function validateConfig(input) {
  const config = {};
  for (const [name, limit] of Object.entries(LIMITS)) {
    const value = input[name] ?? "";
    if (typeof value !== "string") return { error: `${name} must be text` };
    if (value.includes("\0")) return { error: `${name} must not contain NUL` };
    if (bytes(value) > limit) return { error: `${name} exceeds ${limit} UTF-8 bytes` };
    if (value === "" && name !== "scaleAddress" && name !== "wifiPassword") {
      return { error: `${name} is required` };
    }
    config[name] = value;
  }
  if (!DEVICE_ID.test(config.deviceId)) {
    return { error: "deviceId must be 1-128 letters, digits, '.', '_', ':' or '-'" };
  }
  if (config.scaleAddress && !MAC.test(config.scaleAddress)) {
    return { error: "scaleAddress must be empty or a Bluetooth address such as AA:BB:CC:DD:EE:FF" };
  }
  const urlError = receiverUrlError(config.receiverUrl);
  return urlError ? { error: urlError } : { config };
}

function receiverUrlError(text) {
  let url;
  try {
    url = new URL(text);
  } catch {
    return "receiverUrl must be an http(s) URL";
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return "receiverUrl must be an http(s) URL";
  if (!url.hostname) return "receiverUrl is missing a host";
  if (url.username || url.password) return "receiverUrl must not contain credentials";
  if (text.includes("?")) return "receiverUrl must not contain a query";
  if (text.includes("#")) return "receiverUrl must not contain a fragment";
  if (url.pathname.replace(/\/+$/, "") === "/api/scale-readings") {
    return "receiverUrl is a base URL; do not include /api/scale-readings";
  }
  return null;
}

/** Split serial text into complete JSON event objects; return them and the unfinished tail. */
export function parseEvents(buffer) {
  const lines = buffer.split("\n");
  const rest = lines.pop();
  const events = [];
  for (const line of lines) {
    const text = line.trim();
    if (!text.startsWith("{")) continue;
    try {
      const value = JSON.parse(text);
      if (value && typeof value === "object" && typeof value.event === "string") events.push(value);
    } catch {
      // Boot logs share the console; ignore anything that is not a JSON event.
    }
  }
  return { events, rest: rest.length > 4096 ? "" : rest };
}
