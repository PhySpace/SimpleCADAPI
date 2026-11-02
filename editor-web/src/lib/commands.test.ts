import { describe, expect, it } from "vitest";

import { commandGroups, pushRecent, searchCommands, type Command } from "./commands";

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
