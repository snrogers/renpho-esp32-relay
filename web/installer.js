import { ESPLoader, Transport } from "https://cdn.jsdelivr.net/npm/esptool-js@0.6.1/bundle.js";

import { parseEvents, validateConfig } from "./config.js";
import { describeProgress, writeFraction } from "./progress.js";

const ESPRESSIF_VID = 0x303a;
const CONSOLE_BAUD = 115200;
const FLASH_BAUD = 921600;
const FLASH_BYTES = 16 * 1024 * 1024;

const $ = (id) => document.getElementById(id);
const logBox = $("log");
let busy = false;

function log(text) {
  logBox.textContent += `${text}\n`;
  logBox.scrollTop = logBox.scrollHeight;
}

const terminal = {
  clean() {},
  write(text) { logBox.textContent += text; },
  writeLine(text) { log(text); },
};

/**
 * The progress panel under one section: the current step, a bar, and a detail line.
 * The bar moves while the amount of work is known and is animated while it is not.
 */
function activity(name, steps) {
  const panel = $(`${name}-activity`);
  const phase = panel.querySelector(".phase");
  const bar = panel.querySelector("progress");
  const detail = panel.querySelector(".detail");
  let started = 0;

  panel.hidden = false;
  panel.dataset.state = "running";
  return {
    step(index, text) {
      phase.textContent = `Step ${index} of ${steps}: ${text}`;
      bar.hidden = false;
      bar.removeAttribute("value");
      detail.textContent = "";
      started = performance.now();
    },
    amount(fraction, totalBytes = 0) {
      bar.max = 1;
      bar.value = fraction;
      detail.textContent = describeProgress({ fraction, totalBytes, elapsedMs: performance.now() - started });
    },
    done(text) {
      panel.dataset.state = "done";
      phase.textContent = `Done: ${text}`;
      bar.hidden = true;
      detail.textContent = "";
    },
    fail(text) {
      panel.dataset.state = "failed";
      phase.textContent = `Stopped: ${text}`;
      bar.hidden = true;
      detail.textContent = "The log below has the details.";
    },
  };
}

function choosePort(ui) {
  ui.step(1, "Choose the board's port in the browser dialog");
  return navigator.serial.requestPort({ filters: [{ usbVendorId: ESPRESSIF_VID }] });
}

/** Run one button action at a time, report failures, and release the buttons. */
async function exclusive(name, steps, action) {
  if (busy) return;
  busy = true;
  for (const button of document.querySelectorAll("button")) button.disabled = true;
  const ui = activity(name, steps);
  try {
    await action(ui);
  } catch (error) {
    const message = error?.name === "NotFoundError" ? "no port selected" : (error?.message ?? String(error));
    log(error?.name === "NotFoundError" ? "No port selected." : `Error: ${message}`);
    ui.fail(message);
  } finally {
    busy = false;
    for (const button of document.querySelectorAll("button")) button.disabled = false;
  }
}

async function withLoader(port, ui, step, work) {
  ui.step(step, "Connect to the board");
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

async function backup(ui) {
  // Ask for the port first: the browser shows its dialog only right after a click.
  const port = await choosePort(ui);
  let image;
  await withLoader(port, ui, 2, async (loader) => {
    ui.step(3, "Read the flash");
    log("Reading all 16 MB of flash. This takes 15 minutes or more.");
    image = await loader.readFlash(0, FLASH_BYTES, (_packet, done, total) => ui.amount(done / total, total));
  });
  ui.step(4, "Save the file");
  const name = `relay-backup-${new Date().toISOString().replace(/[:.]/g, "-")}.bin`;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([image], { type: "application/octet-stream" }));
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
  log(`Saved ${name} (${image.length} bytes). Keep it private: it can contain your Wi-Fi password.`);
  ui.done(`saved ${name}`);
}

async function download(ui) {
  ui.step(2, "Download the firmware");
  const manifest = await (await fetch("firmware/manifest.json", { cache: "no-cache" })).json();
  const totalBytes = manifest.parts.reduce((sum, part) => sum + part.size, 0);
  const fileArray = [];
  let received = 0;
  ui.amount(0, totalBytes);
  for (const part of manifest.parts) {
    const response = await fetch(`firmware/${part.path}`, { cache: "no-cache" });
    if (!response.ok) throw new Error(`cannot download ${part.path}`);
    const data = new Uint8Array(await response.arrayBuffer());
    if (data.length !== part.size) throw new Error(`${part.path} has the wrong size`);
    fileArray.push({ address: part.address, data });
    received += data.length;
    ui.amount(received / totalBytes, totalBytes);
  }
  return { manifest, fileArray, totalBytes };
}

async function install(ui) {
  const port = await choosePort(ui);
  const { manifest, fileArray, totalBytes } = await download(ui);
  const sizes = fileArray.map((file) => file.data.length);
  await withLoader(port, ui, 3, async (loader) => {
    ui.step(4, "Write the firmware");
    log(`Installing firmware ${manifest.version}. Settings and stored readings are kept.`);
    await loader.writeFlash({
      compress: true,
      eraseAll: false,
      fileArray,
      flashFreq: manifest.flashFreq,
      flashMode: manifest.flashMode,
      flashSize: manifest.flashSize,
      reportProgress: (index, written, total) => ui.amount(writeFraction(sizes, index, written, total), totalBytes),
    });
    ui.step(5, "Restart the board");
  });
  log("Firmware installed. The board restarts.");
  ui.done(`firmware ${manifest.version} installed. The board restarts`);
}

/** Open the relay's USB console, run one exchange, and always release the port. */
async function withConsole(port, exchange) {
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

function summary(reply) {
  if (!reply.configured) return "the relay is not configured";
  const parts = [reply.wifiConnected ? "on Wi-Fi" : "not on Wi-Fi"];
  parts.push(reply.scaleAddress ? `paired with ${reply.scaleAddress}` : "not paired. Step onto the scale");
  parts.push(`${reply.queued} queued`);
  return parts.join(", ");
}

function showStatus(reply) {
  const { event, ...fields } = reply;
  log(`Status: ${JSON.stringify(fields)}`);
  if (reply.configured && reply.scaleAddress === "") log("The relay is looking for a scale. Step onto the scale to pair it.");
}

async function configure(ui, form) {
  const { config, error } = validateConfig(Object.fromEntries(new FormData(form)));
  if (error) {
    log(`Check the form: ${error}`);
    ui.fail(`check the form: ${error}`);
    return;
  }
  const port = await choosePort(ui);
  await withConsole(port, async ({ next, send, status }) => {
    ui.step(2, "Wait for the relay to answer");
    await status(15000);
    ui.step(3, "Send the settings");
    await send({ command: "configure", ...config });
    if (!(await next(["configured"], 10000))) throw new Error("the relay did not confirm the configuration");
    log("Configured. The board restarts with the new settings.");
  });
  form.elements.wifiPassword.value = "";
  ui.done("settings saved. The board restarts with them");
}

async function readStatus(ui) {
  const port = await choosePort(ui);
  const reply = await withConsole(port, async ({ status }) => {
    ui.step(2, "Wait for the relay to answer");
    return status(15000);
  });
  showStatus(reply);
  ui.done(summary(reply));
}

if (!("serial" in navigator)) {
  $("unsupported").hidden = false;
  for (const button of document.querySelectorAll("button")) button.disabled = true;
} else {
  $("backup").addEventListener("click", () => exclusive("backup", 4, backup));
  $("install").addEventListener("click", () => exclusive("install", 5, install));
  $("status").addEventListener("click", () => exclusive("status", 2, readStatus));
  $("config").addEventListener("submit", (event) => {
    event.preventDefault();
    exclusive("config", 3, (ui) => configure(ui, event.target));
  });
  fetch("firmware/manifest.json", { cache: "no-cache" })
    .then((response) => response.json())
    .then((manifest) => { $("version").textContent = manifest.version; })
    .catch(() => { $("version").textContent = "not available"; });
}
