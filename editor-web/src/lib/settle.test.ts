// Run with: node --test src/lib/settle.test.ts   (Node >= 22.6 strips the types)
import assert from "node:assert/strict";
import { mock, test } from "node:test";

import { createSettler } from "./settle.ts";

function setup(delay = 250) {
  mock.timers.enable({ apis: ["setTimeout"] });
  const sent: Record<string, number>[] = [];
  const settler = createSettler<number>(delay, (values) => sent.push(values));
  return { sent, settler };
}

test("a burst of changes is sent once, after it stops", () => {
  const { sent, settler } = setup();
  for (let step = 1; step <= 20; step++) {
    settler.push("j1", step);
    mock.timers.tick(100); // faster than the delay: the drag never pauses
  }
  assert.equal(sent.length, 0);
  mock.timers.tick(250);
  assert.deepEqual(sent, [{ j1: 20 }]);
  mock.reset();
});

test("a pause in the middle of a drag sends what is there", () => {
  const { sent, settler } = setup();
  settler.push("j1", 5);
  mock.timers.tick(300);
  settler.push("j1", 9);
  mock.timers.tick(300);
  assert.deepEqual(sent, [{ j1: 5 }, { j1: 9 }]);
  mock.reset();
});

test("flush sends at once and cancels the wait", () => {
  const { sent, settler } = setup();
  settler.push("j1", 7);
  settler.flush();
  assert.deepEqual(sent, [{ j1: 7 }]);
  mock.timers.tick(1000);
  assert.equal(sent.length, 1);
  mock.reset();
});

test("the latest value of each parameter wins, and all of them go together", () => {
  const { sent, settler } = setup();
  settler.push("j1", 1);
  settler.push("j2", 2);
  settler.push("j1", 3);
  settler.flush();
  assert.deepEqual(sent, [{ j1: 3, j2: 2 }]);
  mock.reset();
});

test("flush with nothing pending sends nothing", () => {
  const { sent, settler } = setup();
  settler.flush();
  assert.equal(sent.length, 0);
  mock.reset();
});

test("cancel drops what is pending", () => {
  const { sent, settler } = setup();
  settler.push("j1", 1);
  settler.cancel();
  mock.timers.tick(1000);
  assert.equal(sent.length, 0);
  mock.reset();
});
