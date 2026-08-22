import { createLowlight } from 'lowlight'

import bash from 'highlight.js/lib/languages/bash'
import c from 'highlight.js/lib/languages/c'
import cpp from 'highlight.js/lib/languages/cpp'
import csharp from 'highlight.js/lib/languages/csharp'
import css from 'highlight.js/lib/languages/css'
import go from 'highlight.js/lib/languages/go'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import plaintext from 'highlight.js/lib/languages/plaintext'
import python from 'highlight.js/lib/languages/python'
import rust from 'highlight.js/lib/languages/rust'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import yaml from 'highlight.js/lib/languages/yaml'

/** Syntax highlighting for code blocks, bundled rather than fetched.
 *
 *  Registered by hand instead of `createLowlight(common)`: `common` pulls in
 *  ~40 grammars, most of which nobody studying here will type. These are the
 *  ones worth the bytes, with Python and SQL first because they are what the
 *  notes in this app are actually full of.
 */
export const lowlight = createLowlight({
  python, sql, javascript, typescript, java, cpp, c, csharp, go, rust,
  bash, json, yaml, markdown, css, plaintext,
})

/** Offered in the code block's language picker, in this order. */
export const LANGUAGES = [
  ['python', 'Python'],
  ['sql', 'SQL'],
  ['javascript', 'JavaScript'],
  ['typescript', 'TypeScript'],
  ['java', 'Java'],
  ['cpp', 'C++'],
  ['c', 'C'],
  ['csharp', 'C#'],
  ['go', 'Go'],
  ['rust', 'Rust'],
  ['bash', 'Shell'],
  ['json', 'JSON'],
  ['yaml', 'YAML'],
  ['markdown', 'Markdown'],
  ['css', 'CSS'],
  ['plaintext', 'Plain text'],
] as const
