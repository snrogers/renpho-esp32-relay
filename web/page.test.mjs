import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const page = readFileSync(new URL("./index.html", import.meta.url), "utf8");

test("the backup step is marked optional and warns that it takes 15 minutes or more", () => {
  const section = page.slice(page.indexOf("1. Back up the board"), page.indexOf('id="backup"'));
  assert.match(section, /\(optional\)/);
  assert.match(section, /You can skip this step/);
  assert.match(section, /class="warn">This takes 15 minutes or more\./);
});
