import { describe, expect, it } from "vitest";

import { commandsFromSpecs, visibleCommands, commandGroups, contextKind, contextualActions, fitScore, plainLabel, pushRecent, searchCommands, selectionContext, selectionHint, whenFor, type Command } from "./commands";

const make = (id: string, label: string, group: string, keywords: string[] = [], description = ""): Command => ({ id, label, group, keywords, description, run: () => undefined });
const commands = [
  make("box", "Box", "Primitives", ["cube"], "A rectangular block"),
  make("hole", "Hole", "Features", ["drill"], "A round hole"),
  make("fillet", "Fillet", "Features", ["round"], "Round the picked edges."),
  make("chamfer", "Chamfer", "Features", ["bevel"], "Bevel the picked edges."),
  make("linear_pattern", "Linear pattern", "Pattern", ["array"], "Copies along a direction"),
  make("op.loft_rsolid", "Loft → solid", "Solids", [], "A solid through profiles"),
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
  it("lists groups in the order of the data", () => expect(commandGroups(commands)).toEqual(["Primitives", "Features", "Pattern", "Solids"]));
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
    expect(context).toEqual({ sketches: 1, curves: 0, solids: 1, components: 0, faces: 3, planarFaces: 2, edges: 1, vertices: 0 });
    expect(contextKind(selectionContext([]))).toBeNull();
  });
  it("offers a curve a sweep along it, and with a sketch the sketch swept along it", () => {
    const curve = selectionContext([], [], ["rail"]);
    expect(contextKind(curve)).toBe("curve");
    expect(whenFor("sweep_along")?.(curve)).toBe(true);
    expect(whenFor("sweep_along")?.(selectionContext([], ["ring"], ["rail"]))).toBe(true);
    expect(whenFor("sweep_along")?.(selectionContext([], [], ["rail", "rail2"]))).toBe(false);
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

describe("command visibility and presets", () => {
  const slot = (name: string) => ({ name, label: name, kind: "enum" as const });
  const spec = (id: string, label: string, slots: string[] = []) => ({ id, label, group: "Ops", role: "build", produces: "solid", description: "", slots: slots.map(slot) });
  const opened: { id: string; preset?: Record<string, unknown> }[] = [];
  const registry = commandsFromSpecs(
    [spec("box", "Box"), spec("cut", "Cut"), spec("union", "Union"), spec("intersect", "Intersect"), spec("cut_sketch", "Cut sketch"), spec("boss_sketch", "Boss sketch"), spec("hole", "Hole"), spec("fillet", "Fillet"), spec("extrude_sketch", "Extrude sketch", ["profile", "operation"])],
    (s, preset) => opened.push({ id: s.id, preset }),
  );
  const ids = (openBodies: number) => visibleCommands(registry, { openBodies }).map((c) => c.id);

  it("hides the stand-alone combine commands unless several bodies are open", () => {
    for (const openBodies of [0, 1]) {
      expect(ids(openBodies)).toEqual(expect.arrayContaining(["box", "hole", "fillet"]));
      for (const id of ["cut", "union", "intersect", "cut_sketch", "boss_sketch"]) expect(ids(openBodies)).not.toContain(id);
    }
    for (const id of ["cut", "union", "intersect", "cut_sketch", "boss_sketch"]) expect(ids(2)).toContain(id);
  });
  it("offers only Extrude without a body, Extrude (join) and (cut) with one", () => {
    expect(ids(0).filter((id) => id.startsWith("extrude"))).toEqual(["extrude_sketch"]);
    expect(ids(1).filter((id) => id.startsWith("extrude"))).toEqual(["extrude_sketch_join", "extrude_sketch_cut"]);
    expect(ids(3).filter((id) => id.startsWith("extrude"))).toEqual(["extrude_sketch_join", "extrude_sketch_cut"]);
  });
  it("opens the same dialog with the operation preset", () => {
    const cut = registry.find((c) => c.id === "extrude_sketch_cut");
    expect(cut?.label).toBe("Extrude (cut)");
    expect(cut?.preset).toEqual({ operation: "cut" });
    cut?.run();
    registry.find((c) => c.id === "extrude_sketch_join")?.run();
    registry.find((c) => c.id === "extrude_sketch")?.run();
    expect(opened).toEqual([
      { id: "extrude_sketch", preset: { operation: "cut" } },
      { id: "extrude_sketch", preset: { operation: "join" } },
      { id: "extrude_sketch", preset: undefined },
    ]);
  });
  it("gives a selected sketch Extrude only without a body, the presets with one; Hole and Fillet stay as they are", () => {
    const context = selectionContext([], ["s"]);
    const labels = (openBodies: number) => contextualActions(visibleCommands(registry, { openBodies }), context).map((a) => a.label);
    expect(labels(0)).toEqual(["Extrude"]);
    expect(labels(1)).toEqual(["Extrude (join)", "Extrude (cut)"]);
    expect(labels(2)).toEqual(["Extrude (join)", "Extrude (cut)", "Cut", "Boss"]);
    expect(contextualActions(visibleCommands(registry, { openBodies: 1 }), selectionContext([{ kind: "face" }])).map((a) => a.label)).toEqual(["Hole here"]);
    expect(contextualActions(visibleCommands(registry, { openBodies: 1 }), selectionContext([{ kind: "edge" }])).map((a) => a.label)).toEqual(["Fillet"]);
  });
  it("keeps the plain Extrude when the server has no operation slot to preset", () => {
    const old = commandsFromSpecs([spec("extrude_sketch", "Extrude sketch", ["profile"])], () => undefined);
    expect(old.map((c) => c.id)).toEqual(["extrude_sketch"]);
    expect(visibleCommands(old, { openBodies: 1 })).toHaveLength(1);
  });
});
