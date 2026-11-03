import { describe, expect, it } from "vitest";

import { commandGroups, contextKind, contextualActions, fitScore, plainLabel, pushRecent, searchCommands, selectionContext, selectionHint, whenFor, type Command } from "./commands";

const make = (id: string, label: string, group: string, keywords: string[] = [], description = ""): Command => ({ id, label, group, keywords, description, run: () => undefined });
const commands = [
  make("box", "Box", "Primitives", ["cube"], "A rectangular block"),
  make("hole", "Hole", "Features", ["drill"], "A round hole"),
  make("fillet", "Fillet", "Features", ["round"], "Round the picked edges."),
  make("chamfer", "Chamfer", "Features", ["bevel"], "Bevel the picked edges."),
  make("linear_pattern", "Linear pattern", "Pattern", ["array"], "Copies along a direction"),
  make("loft_rects", "Loft rectangles", "Profiles", [], "A solid between rectangles"),
];

describe("searchCommands", () => {
  it("opens Fillet for fil", () => expect(searchCommands(commands, "fil")[0].id).toBe("fillet"));
  it("matches synonyms and descriptions", () => {
    expect(searchCommands(commands, "drill").map((c) => c.id)).toEqual(["hole"]);
    expect(searchCommands(commands, "bevel")[0].id).toBe("chamfer");
    expect(searchCommands(commands, "rectangular")[0].id).toBe("box");
  });
  it("matches a later word, the group and several words", () => {
    expect(searchCommands(commands, "pattern")[0].id).toBe("linear_pattern");
    expect(searchCommands(commands, "pat lin")[0].id).toBe("linear_pattern");
    expect(searchCommands(commands, "features").map((c) => c.group)).toEqual(["Features", "Features", "Features"]);
  });
  it("is forgiving with skipped letters", () => expect(searchCommands(commands, "fllt").map((c) => c.id)).toEqual(["fillet"]));
  it("puts prefix matches before others and recent ones first among equals", () => {
    expect(searchCommands(commands, "ho")[0].id).toBe("hole");
    expect(searchCommands(commands, "", ["chamfer", "box"]).slice(0, 2).map((c) => c.id)).toEqual(["chamfer", "box"]);
  });
  it("finds nothing for gibberish", () => expect(searchCommands(commands, "zzzq")).toEqual([]));
});

describe("registry helpers", () => {
  it("lists groups in the order of the data", () => expect(commandGroups(commands)).toEqual(["Primitives", "Features", "Pattern", "Profiles"]));
  it("keeps recents unique, newest first, bounded", () => {
    expect(pushRecent(["a", "b"], "b")).toEqual(["b", "a"]);
    expect(pushRecent(Array.from({ length: 12 }, (_, i) => `x${i}`), "n")).toHaveLength(12);
  });
});

describe("what the selection offers", () => {
  const when = (id: string) => whenFor(id);
  const reg = (id: string, label: string, group = "Features"): Command => ({ id, label, group, keywords: [], description: "", when: when(id), run: () => undefined });
  const registry = [
    reg("box", "Box", "Primitives"),
    reg("hole", "Hole"),
    reg("shell", "Shell"),
    reg("fillet", "Fillet"),
    reg("chamfer", "Chamfer"),
    reg("sketch", "Sketch", "Sketch"),
    reg("sketch_on_face", "Sketch on face", "Sketch"),
    reg("edit_sketch", "Edit sketch", "Sketch"),
    reg("boss_sketch", "Boss from sketch", "Sketch"),
    reg("cut_sketch", "Cut with sketch", "Sketch"),
    reg("extrude_sketch", "Extrude", "Sketch"),
    reg("revolve_sketch", "Revolve", "Sketch"),
    reg("translate", "Move", "Transform"),
    reg("rotate", "Rotate", "Transform"),
    reg("mirror", "Mirror", "Transform"),
    reg("linear_pattern", "Linear pattern", "Pattern"),
  ];
  const labels = (context: ReturnType<typeof selectionContext>) => contextualActions(registry, context).map((a) => a.label);

  it("counts a selection by kind, a face of unknown kind counting as flat", () => {
    const context = selectionContext([{ kind: "face", geometry: { type: "plane" } }, { kind: "face", geometry: { type: "cylinder" } }, { kind: "face" }, { kind: "edge" }, { kind: "solid" }], ["s1"]);
    expect(context).toEqual({ sketches: 1, solids: 1, components: 0, faces: 3, planarFaces: 2, edges: 1, vertices: 0 });
    expect(contextKind(selectionContext([]))).toBeNull();
  });
  it("offers a face: sketch on it, a hole, a shell", () => {
    expect(labels(selectionContext([{ kind: "face" }]))).toEqual(["Sketch on this face", "Hole here", "Shell"]);
    expect(labels(selectionContext([{ kind: "face" }, { kind: "face" }]))).toEqual(["Shell"]);
  });
  it("offers edges: fillet and chamfer", () => expect(labels(selectionContext([{ kind: "edge" }, { kind: "edge" }]))).toEqual(["Fillet", "Chamfer"]));
  it("offers a sketch: extrude, revolve, cut, boss, edit", () => {
    expect(labels(selectionContext([], ["s"]))).toEqual(["Extrude", "Revolve", "Cut", "Boss", "Edit sketch"]);
    expect(labels(selectionContext([], ["s", "t"]))).toEqual([]);
  });
  it("offers a body: move, rotate, mirror, pattern", () => expect(labels(selectionContext([{ kind: "solid" }]))).toEqual(["Move", "Rotate", "Mirror", "Pattern"]));
  it("offers nothing for nothing, and a vertex alone has no actions", () => {
    expect(labels(selectionContext([]))).toEqual([]);
    expect(labels(selectionContext([{ kind: "vertex" }]))).toEqual([]);
  });
  it("puts the commands that fit the selection first in a search, in the order of the buttons", () => {
    const context = selectionContext([], ["s"]);
    const found = searchCommands(registry, "", [], fitScore(context)).map((c) => c.id);
    expect(found.slice(0, 5)).toEqual(["extrude_sketch", "revolve_sketch", "cut_sketch", "boss_sketch", "edit_sketch"]);
    expect(searchCommands(registry, "cut", [], fitScore(context))[0].id).toBe("cut_sketch");
  });
  it("leaves the order alone for no selection", () => {
    expect(searchCommands(registry, "", [], fitScore(selectionContext([]))).map((c) => c.id)).toEqual(registry.map((c) => c.id));
  });
  it("says in one line what the selection can do", () => {
    expect(selectionHint(selectionContext([], ["s"]), registry)).toBe("1 sketch selected: extrude, revolve, cut, boss or edit sketch.");
    expect(selectionHint(selectionContext([{ kind: "edge" }]), registry)).toBe("1 edge selected: fillet or chamfer.");
    expect(selectionHint(selectionContext([]), registry)).toBeNull();
  });
  it("uses plain words for the operations", () => {
    expect(plainLabel("extrude_sketch", "Extrude sketch")).toBe("Extrude");
    expect(plainLabel("box", "Box")).toBe("Box");
  });
});
