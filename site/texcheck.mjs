// Reads a JSON array of {where, html} from stdin and parses every \( \) and \[ \] segment with MathJax,
// using the same macros as the site (macros.json). Prints one line per error; exit code 1 if any.
import {readFileSync} from 'fs';
import {mathjax} from 'mathjax-full/js/mathjax.js';
import {TeX} from 'mathjax-full/js/input/tex.js';
import {liteAdaptor} from 'mathjax-full/js/adaptors/liteAdaptor.js';
import {RegisterHTMLHandler} from 'mathjax-full/js/handlers/html.js';
import {AllPackages} from 'mathjax-full/js/input/tex/AllPackages.js';

const macros = JSON.parse(readFileSync(new URL('./macros.json', import.meta.url), 'utf8'));
const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
const tex = new TeX({packages: AllPackages.filter(p => p !== 'bussproofs'), macros,
                     formatError: (jax, err) => { throw err; }});
const doc = mathjax.document('', {InputJax: tex});

let input = '';
for await (const chunk of process.stdin) input += chunk;
const items = JSON.parse(input);
let bad = 0;
const re = /\\\(([\s\S]*?)\\\)|\\\[([\s\S]*?)\\\]/g;
const unescape = s => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
for (const {where, html} of items) {
  const stripped = html.replace(re, '');
  if (/\\\(|\\\)|\\\[|\\\]/.test(stripped)) { console.log(`${where}: unbalanced math delimiters`); bad++; }
  if (/\$/.test(stripped)) { console.log(`${where}: stray $ outside math`); bad++; }
  for (const m of html.matchAll(re)) {
    const src = unescape(m[1] ?? m[2]);
    // Hebrew is fine inside \text{...}, nowhere else
    if (/[֐-׿]/.test(src.replace(/\\text\{[^{}]*\}/g, ''))) {
      console.log(`${where}: Hebrew outside \\text in math: ${src.slice(0, 60)}`); bad++;
    }
    try { doc.convert(src, {display: m[2] !== undefined}); }
    catch (e) { console.log(`${where}: TeX error "${e.message}" in: ${src.slice(0, 80)}`); bad++; }
  }
}
process.exit(bad ? 1 : 0);
