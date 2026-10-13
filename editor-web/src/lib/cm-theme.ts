import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";

/** Code on the cell's own ground; color only where it carries meaning: names (blue),
 * literals (orange), strings (green), comments (dim).  Every color is a CSS variable of
 * the page (index.css), so one theme serves light and dark and follows a switch live. */
const theme = EditorView.theme(
  {
    "&": { color: "var(--foreground)", backgroundColor: "transparent", fontSize: "12px" },
    ".cm-content": { caretColor: "var(--focus)", padding: "6px 0" },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--focus)", borderLeftWidth: "2px" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
      backgroundColor: "var(--code-selection)",
    },
    ".cm-activeLine": { backgroundColor: "transparent" },
    ".cm-gutters": { display: "none" },
    ".cm-line": { padding: "0 10px" },
    // completion and lint popups sit on the page, not on the cell
    ".cm-tooltip": {
      backgroundColor: "var(--popover)",
      color: "var(--popover-foreground)",
      border: "2px solid var(--border)",
    },
    ".cm-tooltip-autocomplete": { fontSize: "12px" },
    ".cm-tooltip-autocomplete > ul": { fontFamily: "var(--mono)", maxHeight: "16em" },
    ".cm-tooltip-autocomplete ul li": { padding: "2px 8px" },
    ".cm-tooltip-autocomplete ul li[aria-selected]": {
      backgroundColor: "var(--primary)",
      color: "var(--primary-foreground)",
    },
    ".cm-completionDetail": { color: "var(--muted-foreground)", fontStyle: "normal", marginLeft: "1em" },
    ".cm-tooltip-autocomplete ul li[aria-selected] .cm-completionDetail": { color: "inherit", opacity: "0.75" },
    ".cm-completionMatchedText": { textDecoration: "none", color: "var(--focus)", fontWeight: "700" },
    ".cm-tooltip-autocomplete ul li[aria-selected] .cm-completionMatchedText": { color: "inherit" },
    ".cm-completionIcon": { opacity: "0.6" },
    ".cm-completionInfo": {
      backgroundColor: "var(--popover)",
      color: "var(--popover-foreground)",
      border: "2px solid var(--border)",
      padding: "6px 8px",
      maxWidth: "420px",
    },
    ".sca-api-signature": { color: "var(--name)", wordBreak: "break-word" },
    ".sca-api-doc": { marginTop: "4px", color: "var(--muted-foreground)" },
    // the parameter to fill in next
    ".cm-snippetField": { backgroundColor: "var(--code-selection)", outline: "1px solid var(--focus)" },
  },
  { dark: false },
);

const highlight = HighlightStyle.define([
  { tag: [tags.keyword, tags.controlKeyword, tags.definitionKeyword, tags.moduleKeyword], color: "var(--foreground)", fontWeight: "700" },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: "var(--name)" },
  { tag: [tags.definition(tags.variableName), tags.className], color: "var(--name)" },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: "var(--focus)" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--pass)" },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: "var(--comment)", fontStyle: "italic" },
  { tag: [tags.operator, tags.punctuation, tags.bracket], color: "var(--muted-foreground)" },
  { tag: tags.self, color: "var(--foreground)", fontStyle: "italic" },
]);

export const cadTheme = [theme, syntaxHighlighting(highlight)];
