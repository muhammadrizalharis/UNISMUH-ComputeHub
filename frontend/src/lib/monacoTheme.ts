// Tema Monaco "One Dark Pro Darker" (aproksimasi palet tema VS Code populer
// binaryify/OneDark-Pro varian Darker) untuk sel kode notebook & editor file.
// Monaco memakai tokenizer Monarch (bukan TextMate), jadi warna dipetakan ke
// token Monarch terdekat.
//
// SELF-HOST Monaco: default @monaco-editor/react memuat Monaco dari CDN
// jsdelivr — kalau internet kampus lambat/putus, editor GAGAL dimuat padahal
// server lokal sehat. Di sini Monaco DIBUNDEL ke aset build (same-origin) +
// worker via Vite `?worker`, sehingga notebook tetap jalan tanpa internet.

import { loader, type Monaco } from '@monaco-editor/react'
import * as monacoBundle from 'monaco-editor'
import EditorWorker from 'monaco-editor/editor/editor.worker.js?worker'

;(self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
  // Python/markdown hanya butuh worker editor dasar (tanpa ts/css/html/json).
  getWorker: () => new EditorWorker(),
}
loader.config({ monaco: monacoBundle })

export const ONE_DARK_PRO_DARKER = 'one-dark-pro-darker'

let defined = false

export function defineOneDarkProDarker(monaco: Monaco): void {
  if (defined) return
  defined = true
  monaco.editor.defineTheme(ONE_DARK_PRO_DARKER, {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: '', foreground: 'abb2bf', background: '1e2227' },
      { token: 'comment', foreground: '7f848e', fontStyle: 'italic' },
      { token: 'keyword', foreground: 'c678dd' },
      { token: 'keyword.flow', foreground: 'c678dd' },
      { token: 'string', foreground: '98c379' },
      { token: 'string.escape', foreground: '56b6c2' },
      { token: 'number', foreground: 'd19a66' },
      { token: 'number.float', foreground: 'd19a66' },
      { token: 'number.hex', foreground: 'd19a66' },
      { token: 'constant', foreground: 'd19a66' },
      { token: 'type.identifier', foreground: 'e5c07b' },
      { token: 'identifier', foreground: 'abb2bf' },
      { token: 'function', foreground: '61afef' },
      { token: 'tag', foreground: 'e06c75' },
      { token: 'attribute.name', foreground: 'd19a66' },
      { token: 'attribute.value', foreground: '98c379' },
      { token: 'operator', foreground: '56b6c2' },
      { token: 'delimiter', foreground: 'abb2bf' },
      { token: 'regexp', foreground: '98c379' },
    ],
    colors: {
      'editor.background': '#1e2227',
      'editor.foreground': '#abb2bf',
      'editorLineNumber.foreground': '#495162',
      'editorLineNumber.activeForeground': '#abb2bf',
      'editorCursor.foreground': '#528bff',
      'editor.selectionBackground': '#3e4451',
      'editor.inactiveSelectionBackground': '#3e445166',
      'editor.lineHighlightBackground': '#2c313c',
      'editor.findMatchBackground': '#42557b',
      'editor.findMatchHighlightBackground': '#314365',
      'editorWhitespace.foreground': '#3b4048',
      'editorIndentGuide.background': '#3b4048',
      'editorIndentGuide.activeBackground': '#4b5263',
      'editorBracketMatch.background': '#515a6b40',
      'editorBracketMatch.border': '#515a6b',
      'editorBracketHighlight.foreground1': '#e5c07b',
      'editorBracketHighlight.foreground2': '#c678dd',
      'editorBracketHighlight.foreground3': '#56b6c2',
      'editorWidget.background': '#21252b',
      'editorSuggestWidget.background': '#21252b',
      'editorSuggestWidget.selectedBackground': '#2c313a',
      'editorHoverWidget.background': '#21252b',
      'editorGutter.background': '#1e2227',
      'scrollbarSlider.background': '#4e566680',
      'scrollbarSlider.hoverBackground': '#5a637580',
      'scrollbarSlider.activeBackground': '#747d9180',
      'minimap.background': '#1e2227',
    },
  })
}
