import assert from "node:assert/strict";
import { test } from "node:test";

import { parseEvents, validateConfig } from "./config.js";

const VALID = {
  deviceId:     "relay-1",
  receiverUrl:  "http://192.0.2.10:8080",
  wifiPassword: "secret",
  wifiSsid:     "lan",
};

test("accepts a complete config and fills the optional scale address", () => {
  assert.deepEqual(validateConfig(VALID).config, { ...VALID, scaleAddress: "" });
  assert.equal(validateConfig({ ...VALID, scaleAddress: "aa:bb:cc:dd:ee:ff" }).config.scaleAddress, "aa:bb:cc:dd:ee:ff");
  assert.equal(validateConfig({ ...VALID, wifiPassword: "" }).config.wifiPassword, "");
});

test("drops fields the firmware does not take", () => {
  assert.equal("extra" in validateConfig({ ...VALID, extra: "x" }).config, false);
});

test("rejects what flash.py rejects", () => {
  const cases = [
    [{ ...VALID, deviceId: "" }, "deviceId is required"],
    [{ ...VALID, deviceId: "bad id" }, "deviceId must be"],
    [{ ...VALID, wifiSsid: "" }, "wifiSsid is required"],
    [{ ...VALID, wifiSsid: "é".repeat(17) }, "wifiSsid exceeds 32 UTF-8 bytes"],
    [{ ...VALID, wifiPassword: "x".repeat(65) }, "wifiPassword exceeds 64"],
    [{ ...VALID, scaleAddress: "not-a-mac" }, "scaleAddress must be empty or"],
    [{ ...VALID, receiverUrl: "ftp://host" }, "must be an http(s) URL"],
    [{ ...VALID, receiverUrl: "host:8080" }, "must be an http(s) URL"],
    [{ ...VALID, receiverUrl: "http://user:pw@host" }, "credentials"],
    [{ ...VALID, receiverUrl: "http://host/?a=1" }, "query"],
    [{ ...VALID, receiverUrl: "http://host/#x" }, "fragment"],
    [{ ...VALID, receiverUrl: "http://host/api/scale-readings/" }, "base URL"],
  ];
  for (const [input, message] of cases) {
    const { error } = validateConfig(input);
    assert.ok(error?.includes(message), `${JSON.stringify(input)} -> ${error}`);
  }
});

test("parses JSON events among boot logs and keeps the unfinished tail", () => {
  const { events, rest } = parseEvents(
    'I (123) boot: start\n{"event":"status","configured":true}\nnot json {\n{"no":"event"}\n{"event":"conf',
  );
  assert.deepEqual(events, [{ event: "status", configured: true }]);
  assert.equal(rest, '{"event":"conf');
  assert.equal(parseEvents("x".repeat(5000)).rest, "");
});
