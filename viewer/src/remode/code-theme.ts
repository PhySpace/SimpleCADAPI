// Re-studio CodeMirror theme: flat dark navy matching the viewer chrome
// (#0b0e12 editor, #202832 hairlines, restrained syntax palette).

import { HighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { tags as t } from '@lezer/highlight';
import { EditorView } from '@codemirror/view';
import type { Extension } from '@codemirror/state';

const reHighlightStyle = HighlightStyle.define([
  { tag: t.comment, color: '#5b6b7c', fontStyle: 'italic' },
  { tag: [t.keyword, t.moduleKeyword, t.controlKeyword], color: '#b3e36b' },
  { tag: [t.string, t.special(t.string)], color: '#c7a86f' },
  { tag: [t.number, t.bool, t.null], color: '#91b8ed' },
  { tag: [t.function(t.variableName), t.function(t.propertyName)], color: '#a8cdf5' },
  { tag: [t.definition(t.variableName), t.definition(t.function(t.variableName))], color: '#e8f4d2' },
  { tag: [t.className, t.typeName], color: '#e0d5a8' },
  { tag: [t.propertyName], color: '#b8c4d4' },
  { tag: [t.operator, t.punctuation, t.separator, t.bracket], color: '#8ea0b4' },
  { tag: t.self, color: '#eeb9c3' },
  { tag: t.invalid, color: '#ff5c5c' },
]);

const reEditorTheme = EditorView.theme(
  {
    '&': { height: '100%', backgroundColor: '#0b0e12', color: '#c7d3e2' },
    '.cm-content': { caretColor: '#b3e36b', minHeight: '100%' },
    '.cm-scroller': { overflow: 'auto', fontFamily: "'DM Mono', ui-monospace, Menlo, monospace", lineHeight: '1.65' },
    '.cm-gutters': { backgroundColor: '#0d1117', color: '#4b5867', border: 'none', borderRight: '1px solid #202832' },
    '.cm-activeLine': { backgroundColor: 'rgba(179, 227, 107, 0.045)' },
    '.cm-activeLineGutter': { backgroundColor: 'transparent', color: '#8fa0b3' },
    '.cm-selectionBackground, &.cm-focused .cm-selectionBackground': { backgroundColor: '#223041' },
    '.cm-lineNumbers .cm-gutterElement': { minWidth: '34px' },
  },
  { dark: true },
);

/** Drop-in replacement for the default oneDark pair on PythonEditor. */
export const reStudioEditorTheme: Extension[] = [reEditorTheme, syntaxHighlighting(reHighlightStyle)];
