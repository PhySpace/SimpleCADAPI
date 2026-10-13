import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";

/** Black cell, white code; color only where it carries meaning:
 * names (blue), literals (orange), strings (green), comments (dim). */
const theme = EditorView.theme(
  {
    "&": { color: "#ffffff", backgroundColor: "transparent", fontSize: "12px" },
    ".cm-content": { caretColor: "#ff9a2e", padding: "6px 0" },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: "#ff9a2e", borderLeftWidth: "2px" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
      backgroundColor: "#ffffff33",
    },
    ".cm-activeLine": { backgroundColor: "transparent" },
    ".cm-gutters": { display: "none" },
    ".cm-line": { padding: "0 10px" },
  },
  { dark: true },
);

const highlight = HighlightStyle.define([
  { tag: [tags.keyword, tags.controlKeyword, tags.definitionKeyword, tags.moduleKeyword], color: "#ffffff", fontWeight: "700" },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: "#4aa3ff" },
  { tag: [tags.definition(tags.variableName), tags.className], color: "#4aa3ff" },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: "#ff9a2e" },
  { tag: [tags.string, tags.special(tags.string)], color: "#3ddc84" },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: "#777777", fontStyle: "italic" },
  { tag: [tags.operator, tags.punctuation, tags.bracket], color: "#a8a8a8" },
  { tag: tags.self, color: "#ffffff", fontStyle: "italic" },
]);

export const cadTheme = [theme, syntaxHighlighting(highlight)];
