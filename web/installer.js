import { ESPLoader, Transport } from "https://cdn.jsdelivr.net/npm/esptool-js@0.6.1/bundle.js";

import { parseEvents, validateConfig } from "./config.js";

const ESPRESSIF_VID = 0x303a;
const CONSOLE_BAUD = 115200;
const FLASH_BAUD = 921600;
const FLASH_BYTES = 16 * 1024 * 1024;

const $ = (id) => document.getElementById(id);
const logBox = $("log");
const progress = $("progress");
let busy = false;

function log(text) {
  logBox.textContent += `${text}\n`;
  logBox.scrollTop = logBox.scrollHeight;
}

function setProgress(done, total) {
  progress.hidden = total === 0;
  progress.max = total || 1;
  progress.value = done;
}

const terminal = {
  clean() {},
  write(text) { logBox.textContent += text; },
  writeLine(text) { log(text); },
};

function choosePort() {
  return navigator.serial.requestPort({ filters: [{ usbVendorId: ESPRESSIF_VID }] });
}

/** Run one button action at a time, report failures, and release the buttons. */
async function exclusive(action) {
  if (busy) return;
  busy = true;
  for (const button of document.querySelectorAll("button")) button.disabled = true;
  try {
    await action();
  } catch (error) {
    if (error?.name === "NotFoundError") log("No port selected.");
    else log(`Error: ${error?.message ?? error}`);
  } finally {
    setProgress(0, 0);
    busy = false;
    for (const button of document.querySelectorAll("button")) button.disabled = false;
  }
}

async function withLoader(work) {
  const port = await choosePort();
  const transport = new Transport(port, false);
  const loader = new ESPLoader({ transport, baudrate: FLASH_BAUD, terminal });
  try {
    log(`Connected to ${await loader.main()}.`);
    await work(loader);
    await loader.after("hard_reset");
  } finally {
    await transport.disconnect();
  }
}

async function backup() {
  await withLoader(async (loader) => {
    log("Reading all 16 MB of flash. This takes a few minutes.");
    const image = await loader.readFlash(0, FLASH_BYTES, (_packet, done, total) => setProgress(done, total));
    const name = `relay-backup-${new Date().toISOString().replace(/[:.]/g, "-")}.bin`;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([image], { type: "application/octet-stream" }));
    link.download = name;
    link.click();
    URL.revokeObjectURL(link.href);
    log(`Saved ${name} (${image.length} bytes). Keep it private: it can contain your Wi-Fi password.`);
  });
}

async function install() {
  const manifest = await (await fetch("firmware/manifest.json", { cache: "no-cache" })).json();
  const fileArray = [];
  for (const part of manifest.parts) {
    const response = await fetch(`firmware/${part.path}`, { cache: "no-cache" });
    if (!response.ok) throw new Error(`cannot download ${part.path}`);
    const data = new Uint8Array(await response.arrayBuffer());
    if (data.length !== part.size) throw new Error(`${part.path} has the wrong size`);
    fileArray.push({ address: part.address, data });
  }
  const total = fileArray.reduce((sum, file) => sum + file.data.length, 0);
  await withLoader(async (loader) => {
    log(`Installing firmware ${manifest.version}. Settings and stored readings are kept.`);
    await loader.writeFlash({
      compress: true,
      eraseAll: false,
      fileArray,
      flashFreq: manifest.flashFreq,
      flashMode: manifest.flashMode,
      flashSize: manifest.flashSize,
      reportProgress: (index, written) => {
        const before = fileArray.slice(0, index).reduce((sum, file) => sum + file.data.length, 0);
        setProgress(before + written, total);
      },
    });
    log("Firmware installed. The board restarts.");
  });
}

/** Open the relay's USB console, run one exchange, and always release the port. */
async function withConsole(exchange) {
  const port = await choosePort();
  await port.open({ baudRate: CONSOLE_BAUD });
  const decoder = new TextDecoderStream();
  const piped = port.readable.pipeTo(decoder.writable).catch(() => {});
  const reader = decoder.readable.getReader();
  const writer = port.writable.getWriter();
  let buffer = "";
  let pending = null; // One read stays in flight across timeouts, so no data is lost.
  const queue = [];

  const send = (command) => writer.write(new TextEncoder().encode(`${JSON.stringify(command)}\n`));
  const next = async (wanted, timeoutMs) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      while (queue.length) {
        const event = queue.shift();
        if (event.event === "configuration_error") throw new Error(`relay rejected the configuration: ${event.error}`);
        if (wanted.includes(event.event)) return event;
      }
      const timer = new Promise((resolve) => setTimeout(() => resolve({ timeout: true }), Math.min(1000, deadline - Date.now())));
      pending ??= reader.read();
      const chunk = await Promise.race([pending, timer]);
      if (chunk.timeout) return null;
      pending = null;
      if (chunk.done) throw new Error("the board closed the connection");
      const parsed = parseEvents(buffer + chunk.value);
      buffer = parsed.rest;
      queue.push(...parsed.events);
    }
    return null;
  };
  // A board that resets when the port opens answers after it boots: ask until it does.
  const status = async (timeoutMs) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await send({ command: "status" });
      const reply = await next(["status"], 1500);
      if (reply) return reply;
    }
    throw new Error("the relay did not answer. Check the cable and that the relay firmware is installed.");
  };

  try {
    return await exchange({ next, send, status });
  } finally {
    await reader.cancel().catch(() => {});
    await piped;
    writer.releaseLock();
    await port.close().catch(() => {});
  }
}

function showStatus(reply) {
  const { event, ...fields } = reply;
  log(`Status: ${JSON.stringify(fields)}`);
  if (reply.configured && reply.scaleAddress === "") log("The relay is looking for a scale. Step onto the scale to pair it.");
}

async function configure(form) {
  const { config, error } = validateConfig(Object.fromEntries(new FormData(form)));
  if (error) {
    log(`Check the form: ${error}`);
    return;
  }
  await withConsole(async ({ next, send, status }) => {
    await status(15000);
    await send({ command: "configure", ...config });
    if (!(await next(["configured"], 10000))) throw new Error("the relay did not confirm the configuration");
    log("Configured. The board restarts with the new settings.");
  });
  form.elements.wifiPassword.value = "";
}

async function readStatus() {
  await withConsole(async ({ status }) => showStatus(await status(15000)));
}

if (!("serial" in navigator)) {
  $("unsupported").hidden = false;
  for (const button of document.querySelectorAll("button")) button.disabled = true;
} else {
  $("backup").addEventListener("click", () => exclusive(backup));
  $("install").addEventListener("click", () => exclusive(install));
  $("status").addEventListener("click", () => exclusive(readStatus));
  $("config").addEventListener("submit", (event) => {
    event.preventDefault();
    exclusive(() => configure(event.target));
  });
  fetch("firmware/manifest.json", { cache: "no-cache" })
    .then((response) => response.json())
    .then((manifest) => { $("version").textContent = manifest.version; })
    .catch(() => { $("version").textContent = "not available"; });
}
