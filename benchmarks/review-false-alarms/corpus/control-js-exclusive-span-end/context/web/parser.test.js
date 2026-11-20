import { test } from "node:test";
import assert from "node:assert/strict";

import { parseNumberList } from "./parser.js";

test("the error span is end-exclusive", () => {
  assert.throws(() => parseNumberList("1, ab, 3"), (error) => {
    assert.deepEqual(error.span, { start: 3, end: 5 });
    return true;
  });
});
