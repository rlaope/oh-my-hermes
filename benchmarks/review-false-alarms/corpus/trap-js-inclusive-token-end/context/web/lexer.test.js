import { test } from "node:test";
import assert from "node:assert/strict";

import { tokenize } from "./lexer.js";

test("both ends of a token are inclusive", () => {
  assert.deepEqual(tokenize("Ab c"), [
    { text: "ab", start: 0, end: 1 },
    { text: "c", start: 3, end: 3 },
  ]);
});
