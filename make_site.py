#!/usr/bin/env python3
"""Build index.html, the practice site for the exercise bank, from the question files under questions/.

The LaTeX files stay the only source: every run converts them again. A question whose
sub-items each have their own solbox becomes one card per item; any other question is one card.
Solutions are split into steps (paragraphs, list items, and the text after a displayed formula),
which the site reveals one at a time.

Usage:  python3 make_site.py           # writes index.html
        python3 make_site.py --check   # also parses every formula with MathJax (needs: cd site && npm install)
        python3 make_site.py --with-suggested ../lectureNotes9921/exercises/suggested
            # writes preview.html instead (not tracked by git), with the suggested (pink) questions

Suggested questions (header "% suggested: yes") are kept in the course's private repository and stay
out of index.html until they are approved and moved to questions/.
"""
import base64, html, json, os, re, subprocess, sys

from make_bank import load, load_structure, suggested_dir, unreleased

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, 'site')
# Part labels as in the PDF lists (Hebrew numerals): א..ט, י, יא, יב, ...
LETTERS = list('אבגדהוזחט') + ['י', 'יא', 'יב', 'יג', 'יד', 'טו', 'טז', 'יז', 'יח', 'יט', 'כ', 'כא', 'כב']
LATIN = 'abcdefghijklmnopqrstuv'
warnings = []


# ---------------------------------------------------------------- low-level TeX helpers

def strip_comments(s):
    return re.sub(r'(?<!\\)%.*', '', s)


def group(s, i):
    """s[i] == '{' -> (content, index after the closing brace)."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == '\\':
            continue
        if s[j] == '{' and (j == 0 or s[j - 1] != '\\'):
            depth += 1
        elif s[j] == '}' and s[j - 1] != '\\':
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
    raise ValueError('unbalanced braces: ' + s[i:i + 60])


def replace_cmd(s, name, fn, nargs=1):
    r"""Replace \name{a}{b}... by fn(a, b, ...); arguments may contain nested braces."""
    out, i = [], 0
    pat = re.compile(r'\\' + name + r'(?![a-zA-Z])\s*')
    while True:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:])
            return ''.join(out)
        j, args = m.end(), []
        for _ in range(nargs):
            while j < len(s) and s[j] in ' \n':
                j += 1
            if j >= len(s) or s[j] != '{':
                break
            a, j = group(s, j)
            args.append(a)
        if len(args) < nargs:            # not followed by braces: leave as is
            out.append(s[i:m.end()])
            i = m.end()
            continue
        out.append(s[i:m.start()])
        out.append(fn(*args))
        i = j


def strip_iffalse(s):
    r"""Drop \iffalse ... \fi blocks (nested \if... counted)."""
    while True:
        m = re.search(r'\\iffalse\b', s)
        if not m:
            return s
        depth, i = 1, m.end()
        for t in re.finditer(r'\\if[a-zA-Z]*|\\fi\b', s[m.end():]):
            depth += 1 if t.group().startswith('\\if') else -1
            if depth == 0:
                i = m.end() + t.end()
                break
        s = s[:m.start()] + s[i:]


def normalize(body):
    s = strip_comments(body)
    s = strip_iffalse(s)
    s = re.sub(r'\\(begin|end)\{suggested\}', '', s)                 # the pink box of a suggested question
    s = re.sub(r'\\ifsol\b|\\fi\b', '', s)                    # \ifsol only ever wraps a solbox
    s = re.sub(r'\\bE\b', r'\\begin{enumerate}', s)
    s = re.sub(r'\\eE\b', r'\\end{enumerate}', s)
    s = re.sub(r'\\bit\b', r'\\begin{itemize}', s)
    s = re.sub(r'\\eit\b', r'\\end{itemize}', s)
    s = re.sub(r'\\bMs?\{\d\}|\\eMs?\b|\\begin\{multicols\}\{\d\}|\\end\{multicols\}', '', s)
    s = re.sub(r'\\begin\{enumerate\}\s*\[[^\]]*\]', r'\\begin{enumerate}', s)
    s = re.sub(r'\\(newpage|clearpage|noindent|medskip|smallskip|bigskip|centering)\b', '', s)
    s = re.sub(r'\\[vh]space\*?\{[^}]*\}', '', s)
    # \mbox{\(x\)} around a whole formula (app-001)
    s = re.sub(r'\\\(\s*\\mbox\{\\\((.*?)\\\)\}\s*\\\)', r'\\(\1\\)', s)
    s = re.sub(r'\\mbox\{\\\((.*?)\\\)\}', r'\\(\1\\)', s)
    s = re.sub(r'\\(begin|end)\{center\}|\\hfill\b|\\renewcommand\{\\arraystretch\}\{[^}]*\}', '', s)
    # Venn diagrams: a placeholder that survives the text conversion, drawn as SVG by figures()
    s = replace_cmd(s, 'venn', lambda regions, label: f'@@VENN:{regions.replace(" ", "")}:{label}@@', 2)
    return s


# ---------------------------------------------------------------- figures and tables

def venn_svg(regions, label, n=[0]):
    """Three circles A, B, C in a frame; regions lists the shaded ones as a/b/c (1 = inside that set)."""
    n[0] += 1
    k = f'v{n[0]}'
    circles = {'A': (36, 36), 'B': (66, 36), 'C': (51, 61)}
    defs = []
    for name, (cx, cy) in circles.items():
        defs.append(f'<clipPath id="{k}{name}"><circle cx="{cx}" cy="{cy}" r="24"/></clipPath>')
        defs.append(f'<mask id="{k}{name}o"><rect width="104" height="100" fill="#fff"/>'
                    f'<circle cx="{cx}" cy="{cy}" r="24" fill="#000"/></mask>')
    fills = []
    for reg in regions.split(','):
        inside = reg.split('/')
        g = '<rect x="2" y="2" width="100" height="96" class="venn-fill"/>'
        for name, bit in zip('ABC', inside):
            g = (f'<g clip-path="url(#{k}{name})">{g}</g>' if bit == '1' else f'<g mask="url(#{k}{name}o)">{g}</g>')
        fills.append(g)
    lines = ''.join(f'<circle cx="{cx}" cy="{cy}" r="24" class="venn-line"/>' for cx, cy in circles.values())
    text = ('<text x="24" y="27">A</text><text x="78" y="27">B</text><text x="51" y="77">C</text>')
    return (f'<figure class="venn"><svg viewBox="0 0 104 100" width="104" height="100" role="img" '
            f'aria-label="דיאגרמת ון {html.escape(label)}"><defs>{"".join(defs)}</defs>{"".join(fills)}'
            f'<rect x="2" y="2" width="100" height="96" class="venn-line"/>{lines}{text}</svg>'
            f'<figcaption>{html.escape(label)}</figcaption></figure>')


def figures(h):
    h = re.sub(r'@@VENN:([^:@]*):([^@]*)@@', lambda m: venn_svg(m.group(1), m.group(2)), h)
    # diagrams that stand together (one per line in the source) are laid out in one row
    return re.sub(r'((?:<figure class="venn">.*?</figure>\s*(?:<br>\s*)?){2,})',
                  lambda m: '<div class="figs">' + re.sub(r'<br>', '', m.group(1)) + '</div>', h)


def tables_to_html(s):
    r"""tabular -> <table>. Runs on escaped text with the math already replaced by placeholders, so a
    cell separator is &amp;. Rows above the first \hline are headings; a | in the column spec draws a rule."""
    while True:
        m = re.search(r'\\begin\{tabular\}\{([^}]*)\}(.*?)\\end\{tabular\}', s, re.S)
        if not m:
            return s
        spec, rule_after, col = m.group(1), set(), -1
        for ch in spec:
            if ch in 'lcrp':
                col += 1
            elif ch == '|' and col >= 0:
                rule_after.add(col)
        rows, head, seen_hline = [], [], False
        for raw in re.split(r'\\\\', m.group(2)):
            hl = '\\hline' in raw
            if raw.lstrip().startswith('\\hline'):      # a rule under the previous row
                seen_hline = True
            raw = raw.replace('\\hline', '').strip()
            if raw:
                cells = [c.strip() for c in raw.split('&amp;')]
                (rows if seen_hline else head).append(cells)
            seen_hline = seen_hline or hl
        if not rows:
            head, rows = [], head
        def tr(cells, tag):
            return '<tr>' + ''.join(f'<{tag}{" class=rule" if i in rule_after else ""}>{c}</{tag}>'
                                    for i, c in enumerate(cells)) + '</tr>'
        t = ('<div class="tbl-wrap"><table class="tbl">' + ''.join(tr(r, 'th') for r in head) +
             ''.join(tr(r, 'td') for r in rows) + '</table></div>')
        s = s[:m.start()] + '\n' + t + '\n' + s[m.end():]


ENV_RE = re.compile(r'\\(begin|end)\{([a-zA-Z*]+)\}|\\item\b')


def top_level(s, env='enumerate'):
    """Positions of depth-0 \\begin{env} ... \\end{env} blocks: list of (start, content_start, content_end, end)."""
    out, depth, start = [], 0, None
    for m in ENV_RE.finditer(s):
        if m.group(0) == '\\item':
            continue
        if m.group(1) == 'begin':
            if depth == 0 and m.group(2) == env:
                start, cstart = m.start(), m.end()
            depth += 1
        else:
            depth -= 1
            if depth == 0 and start is not None and m.group(2) == env:
                out.append((start, cstart, m.start(), m.end()))
                start = None
    return out


def split_items(s):
    """Split the inside of a list at its depth-0 \\item's. Returns (before first item, [items])."""
    cuts, depth = [], 0
    for m in ENV_RE.finditer(s):
        if m.group(0) == '\\item':
            if depth == 0:
                cuts.append(m)
        elif m.group(1) == 'begin':
            depth += 1
        else:
            depth -= 1
    if not cuts:
        return s, []
    items = [s[c.end():(cuts[k + 1].start() if k + 1 < len(cuts) else len(s))] for k, c in enumerate(cuts)]
    items = [re.sub(r'^\s*\[[^\]]*\]', '', it) for it in items]      # \item[label]
    return s[:cuts[0].start()], items


def solboxes(s):
    """(text without solboxes, [solbox contents]) — only depth-0 solboxes of s."""
    boxes = top_level(s, 'solbox')
    text, last, sols = [], 0, []
    for a, b, c, d in boxes:
        text.append(s[last:a])
        sols.append(s[b:c])
        last = d
    text.append(s[last:])
    return ''.join(text), sols


# ---------------------------------------------------------------- math

DISPLAY_ENVS = ('align*', 'align', 'equation*', 'equation', 'gather*', 'gather', 'multline*')
HEB = re.compile(r'[\u0590-\u05FF]')


class Ctx:
    """Per-question state: equation labels."""
    def __init__(self, qid):
        self.qid, self.labels = qid, {}


def fix_math(src, ctx):
    src = src.strip()
    # Hebrew inside \text: drop the \R wrapper; inner $x$ becomes plain text.
    src = replace_cmd(src, 'R', lambda a: a)
    # A leading RLM makes text that starts with a Latin letter ("n משאיר שארית 1") still run right to left.
    src = replace_cmd(src, 'text', lambda a: r'\text{' + ('\u200f' if HEB.search(a) else '') +
                      re.sub(r'\$([^$]*)\$', r'\1', a) + '}')
    # Word order written backwards for XeLaTeX's bidi; in the browser the text runs right to left on its own.
    src = src.replace('האינדוקציה הנחת', 'הנחת האינדוקציה').replace('היצקודניאה תחנה', 'הנחת האינדוקציה')
    src = re.sub(r'םימעפ\s*\\ n', r'\\text{פעמים}\\ n', src)               # seq-007: letters reversed, no \text
    src = re.sub(r'\\makebox\[[^\]]*\]\[[^\]]*\]', '', src)
    src = re.sub(r'\\nonumber\b|\\notag\b', '', src)

    def label(name):
        n = ctx.labels.setdefault(name, len(ctx.labels) + 1)
        return r'\tag{%d}' % n
    src = replace_cmd(src, 'label', label)
    return src


def math_html(src, display, ctx):
    src = fix_math(src, ctx)
    if not src:
        return ''
    esc = html.escape(src, quote=False)
    return (r'\[' + esc + r'\]') if display else (r'\(' + esc + r'\)')


MATH_RE = re.compile(
    r'\$\$(.+?)\$\$|\\\[(.+?)\\\]|(?<!\\)\$(.+?)(?<!\\)\$|\\\((.+?)\\\)|'
    r'\\begin\{(' + '|'.join(re.escape(e) for e in DISPLAY_ENVS) + r')\}(.*?)\\end\{\5\}', re.S)


def protect_math(s, ctx):
    """Replace math by placeholders; returns (text, [html of each math chunk], [is_display])."""
    chunks, disp = [], []

    def sub(m):
        if m.group(5):
            env, body = m.group(5), m.group(6)
            numbered = not env.endswith('*')
            if env.startswith('align') or env.startswith('gather') or env.startswith('multline'):
                body = r'\begin{aligned}' + body + r'\end{aligned}'
            if not numbered:
                body = re.sub(r'\\label\{[^}]*\}', '', body)
            tags = re.findall(r'\\label\{[^}]*\}', body)
            if len(tags) == 1 and r'\begin{aligned}' in body:      # \tag is not allowed inside aligned
                body = body.replace(tags[0], '') + tags[0]
            h, d = math_html(body, True, ctx), True
        elif m.group(1) is not None or m.group(2) is not None:
            h, d = math_html(m.group(1) if m.group(1) is not None else m.group(2), True, ctx), True
        else:
            h, d = math_html(m.group(3) if m.group(3) is not None else m.group(4), False, ctx), False
        chunks.append(h)
        disp.append(d)
        return '\x00%d\x00' % (len(chunks) - 1)
    return MATH_RE.sub(sub, s), chunks, disp


# ---------------------------------------------------------------- text

def text_cmds(s, ctx, refs):
    s = replace_cmd(s, 'textbf', lambda a: '<b>' + a + '</b>')
    s = re.sub(r'\{\\bf\s+', r'\\textbf{', s)
    s = replace_cmd(s, 'textbf', lambda a: '<b>' + a + '</b>')
    s = replace_cmd(s, 'underline', lambda a: '<u>' + a + '</u>')
    s = replace_cmd(s, 'emph', lambda a: '<i>' + a + '</i>')
    s = replace_cmd(s, 'textit', lambda a: '<i>' + a + '</i>')
    s = replace_cmd(s, 'textenglish', lambda a: a)
    s = replace_cmd(s, 'qref', lambda a: refs.get(a, a))
    num = lambda a: str(ctx.labels.get(a, '?'))
    s = re.sub(r'\)\s*\\ref\{([^}]*)\}\s*\(', lambda m: '(' + num(m.group(1)) + ')', s)   # old RTL-reversed form
    s = replace_cmd(s, 'eqref', lambda a: '(' + num(a) + ')')
    s = replace_cmd(s, 'ref', num)
    s = s.replace('\\\\', '<br>').replace('\\newline', '<br>')
    s = s.replace('``', '"').replace("''", '"').replace('---', '—').replace('--', '–').replace('~', '\u00a0')
    s = re.sub(r'\\(quad|qquad|,|;|enskip|ldots|dots)\b', lambda m: '…' if m.group(1) in ('ldots', 'dots') else ' ', s)
    s = s.replace('\\%', '%').replace('\\&', '&amp;').replace('\\_', '_').replace('\\{', '{').replace('\\}', '}')
    s = re.sub(r'(?<!\\)[{}]', '', s)                                  # leftover grouping braces
    for m in re.finditer(r'\\[a-zA-Z]+', s):
        warnings.append(f'{ctx.qid}: unhandled command {m.group()} in text')
    return s


def convert(tex, ctx, refs, ordered_style='hebrew'):
    """TeX fragment (text mode, may contain lists and math) -> HTML."""
    s, chunks, _ = protect_math(tex, ctx)
    s = html.escape(s, quote=False)
    s = tables_to_html(s)
    s = lists_to_html(s, ctx, refs)
    s = text_cmds(s, ctx, refs)
    paras = [p.strip() for p in re.split(r'\n\s*\n', s) if p.strip()]
    s = '<br>'.join(re.sub(r'\s+', ' ', p) for p in paras) if len(paras) > 1 else (re.sub(r'\s+', ' ', paras[0]) if paras else '')
    s = re.sub(r'(<br>\s*)+(<(ol|ul)|</li>)', r'\2', s)
    s = re.sub(r'(</(ol|ul)>)\s*(<br>\s*)+', r'\1', s)
    return figures(re.sub('\x00(\\d+)\x00', lambda m: chunks[int(m.group(1))], s).strip())


def lists_to_html(s, ctx, refs):
    while True:
        blocks = [(b, 'enumerate') for b in top_level(s, 'enumerate')] + [(b, 'itemize') for b in top_level(s, 'itemize')]
        if not blocks:
            return s
        (a, b, c, d), kind = min(blocks)
        _, items = split_items(s[b:c])
        tag = 'ol' if kind == 'enumerate' else 'ul'
        inner = ''.join('<li>' + lists_to_html(it, ctx, refs).strip() + '</li>' for it in items)
        s = s[:a] + '\n<%s>%s</%s>\n' % (tag, inner, tag) + s[d:]


# ---------------------------------------------------------------- solutions -> steps

def solution_steps(tex, ctx, refs):
    """Split a solution into steps: paragraphs, depth-0 list items, and text that follows a displayed formula."""
    s, chunks, disp = protect_math(tex, ctx)
    raw = []
    # depth-0 lists: each item becomes its own step
    pos = 0
    blocks = sorted([(b, 'enumerate') for b in top_level(s, 'enumerate')] + [(b, 'itemize') for b in top_level(s, 'itemize')])
    for (a, b, c, d), kind in blocks:
        raw += [('p', x) for x in re.split(r'\n\s*\n', s[pos:a])]
        _, items = split_items(s[b:c])
        raw += [('li-' + kind, it) for it in items]
        pos = d
    raw += [('p', x) for x in re.split(r'\n\s*\n', s[pos:])]

    steps = []
    for kind, part in raw:
        if not part.strip():
            continue
        pieces = [part] if kind != 'p' else split_after_display(part, disp)
        for p in pieces:
            h = html.escape(p, quote=False)
            h = tables_to_html(h)
            h = lists_to_html(h, ctx, refs)
            h = text_cmds(h, ctx, refs)
            h = re.sub(r'\s+', ' ', h).strip()
            h = re.sub(r'(<br>\s*)+(<(ol|ul)|</li>)', r'\2', h)
            h = re.sub(r'(</(ol|ul)>)\s*(<br>\s*)+', r'\1', h)
            h = re.sub(r'^(<br>\s*)+|(<br>\s*)+$', '', h)
            h = figures(re.sub('\x00(\\d+)\x00', lambda m: chunks[int(m.group(1))], h).strip())
            if not re.sub(r'<[^>]+>|\s', '', h):
                continue
            if kind.startswith('li-'):
                h = '<ul class="step-item"><li>' + h + '</li></ul>'
            steps.append(h)
    return steps


def split_after_display(part, disp):
    """Cut a paragraph after each displayed formula when real text follows it."""
    out, last = [], 0
    for m in re.finditer('\x00(\\d+)\x00', part):
        if not disp[int(m.group(1))]:
            continue
        rest = part[m.end():]
        follow = re.sub('\x00\\d+\x00', 'x', rest)
        # keep short tails (".", ", כאשר x>0") on the same line
        if len(re.sub(r'[\s.,;:]', '', follow.split('\n\n')[0])) >= 12 and not re.match(r'\s*[.,;:)]', rest):
            out.append(part[last:m.end()])
            last = m.end()
    out.append(part[last:])
    return out


# ---------------------------------------------------------------- questions -> cards

def pull_hint(text, ctx, refs):
    r"""Remove \hint{...} from a card's text -> (text, hint html or '')."""
    found = []
    text = replace_cmd(text, 'hint', lambda h: found.append(h) or '')
    return text, ' '.join(convert(h, ctx, refs) for h in found)


def build_cards(qs, structure, refs):
    cards = []
    for q in qs:
        ctx = Ctx(q['id'])
        body = normalize(q['body'])
        unverified = q.get('verified') == 'no'
        marked = '\\unverified' in body

        def official(sols):
            # a file with \unverified markers: only the solutions that carry one are drafts
            return not unverified or (marked and not any('\\unverified' in x for x in sols))

        def steps_of(sols):
            return [st for sol in sols for st in solution_steps(sol.replace('\\unverified', ''), ctx, refs)]
        base = {'topic': structure[q['subtopic']][2], 'sub': q['subtopic'], 'qid': q['id']}
        if q.get('suggested') == 'yes':
            base['suggested'] = True
        lists = top_level(body, 'enumerate')
        outside, _ = solboxes(body)
        split = None
        if lists:
            a, b, c, d = lists[0]
            head, items = split_items(body[b:c])
            per_item = [solboxes(it) for it in items]
            before, before_sols = solboxes(body[:a])
            after, after_sols = solboxes(body[d:])
            if len(items) > 1 and not head.strip():
                if all(sols for _, sols in per_item) and not after_sols:
                    # a solbox before the list is a remark for every item (app-010)
                    split = (before, [(t, before_sols + s) for t, s in per_item], after)
                elif not any(sols for _, sols in per_item) and not before_sols and len(after_sols) == 1:
                    # one solbox after the list, itself a list with one entry per item (der-001)
                    sol = after_sols[0].strip()
                    inner = top_level(sol, 'enumerate')
                    if len(inner) == 1 and inner[0][3] == len(sol):
                        # text before that list (der-004) is again a remark for every item
                        common = [sol[:inner[0][0]]] if sol[:inner[0][0]].strip() else []
                        _, sol_items = split_items(sol[inner[0][1]:inner[0][2]])
                        if len(sol_items) == len(items):
                            split = (before, [(t, common + [s]) for (t, _), s in zip(per_item, sol_items)], after)
        if split:
            intro, per_item, outro = split
            intro_html = convert(intro + '\n' + outro, ctx, refs) if (intro + outro).strip() else ''
            for k, (text, sols) in enumerate(per_item):
                text, hint = pull_hint(text, ctx, refs)
                part = convert(text, ctx, refs)
                txt = (f'<div class="intro">{intro_html}</div>' if intro_html else '') + \
                      f'<div class="part"><span class="part-letter">{LETTERS[k]}.</span><div>{part}</div></div>'
                steps = steps_of(sols)
                if hint:
                    base_k = dict(base, hint=hint)
                else:
                    base_k = base
                cards.append(dict(base_k, id=f'{q["id"]}{LATIN[k]}', text=txt,
                                  solution={'official': official(sols), 'steps': steps} if steps else None))
        else:
            text, sols = solboxes(body)
            # solboxes nested inside list items (a list whose items don't all have one)
            nested = []
            def pull(m):
                nested.append(m.group(1))
                return ''
            text = re.sub(r'\\begin\{solbox\}(.*?)\\end\{solbox\}', pull, text, flags=re.S)
            text, hint = pull_hint(text, ctx, refs)
            if hint:
                base = dict(base, hint=hint)
            steps = steps_of(sols + nested)
            cards.append(dict(base, id=q['id'], text=convert(text, ctx, refs),
                              solution={'official': official(sols + nested), 'steps': steps} if steps else None))
    return cards


def check_math(cards):
    items = []
    for c in cards:
        items.append({'where': c['id'] + ' (text)', 'html': c['text']})
        for i, st in enumerate((c['solution'] or {}).get('steps', [])):
            items.append({'where': f'{c["id"]} (step {i + 1})', 'html': st})
    r = subprocess.run(['node', os.path.join(SITE, 'texcheck.mjs')], input=json.dumps(items),
                       capture_output=True, text=True, cwd=SITE)
    print(r.stdout + r.stderr, end='')
    return r.returncode == 0


def main():
    extra = suggested_dir()
    preview = extra is not None
    qs = [q for q in load(extra) if preview or q.get('suggested') != 'yes']
    if not preview:                                   # the chapters below the release line stay hidden
        hidden = unreleased()
        qs = [q for q in qs if q['subtopic'] not in hidden]
    structure = load_structure()
    qs.sort(key=lambda q: (structure[q['subtopic']][:2], q['id']))
    # The exercise number in the student booklets: questions run 1, 2, ... in bank order, suggested ones left out.
    book = {q['id']: n for n, q in enumerate((q for q in qs if q.get('suggested') != 'yes'), 1)}
    # \qref{id} becomes the referred exercise's booklet number (the text around it already says "שאלה").
    refs = {q['id']: str(book[q['id']]) if q['id'] in book else 'מהצעה חדשה' for q in qs}
    cards = build_cards(qs, structure, refs)
    for c in cards:
        if c['qid'] in book:
            suffix = c['id'][len(c['qid']):]
            c['book'] = f'{book[c["qid"]]}' + (LETTERS[LATIN.index(suffix)] if suffix else '')

    topics, seen = [], {}
    for sub, (ci, si, chapter) in sorted(structure.items(), key=lambda kv: kv[1][:2]):
        if chapter not in seen:
            seen[chapter] = {'name': chapter, 'subs': []}
            topics.append(seen[chapter])
        if any(c['sub'] == sub for c in cards):
            seen[chapter]['subs'].append(sub)
    topics = [t for t in topics if t['subs']]

    payload = json.dumps({'taxonomy': {'topics': topics}, 'questions': cards},
                         ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    macros = json.load(open(os.path.join(SITE, 'macros.json'), encoding='utf-8'))
    with open(os.path.join(SITE, 'unit-logo.png'), 'rb') as fh:
        logo = 'data:image/png;base64,' + base64.b64encode(fh.read()).decode()
    tpl = open(os.path.join(SITE, 'template.html'), encoding='utf-8').read()
    out = (tpl.replace('/*__DATA__*/', payload).replace('/*__LOGO__*/', logo)
              .replace('/*__MACROS__*/', json.dumps(macros, ensure_ascii=False)))
    target = 'preview.html' if preview else 'index.html'
    open(os.path.join(HERE, target), 'w', encoding='utf-8').write(out)

    for w in sorted(set(warnings)):
        print('WARN', w)
    nsteps = [len(c['solution']['steps']) for c in cards if c['solution']]
    print(f'{target}: {len(qs)} questions -> {len(cards)} cards, '
          f'{sum(nsteps)} solution steps, {len(out.encode()) / 1e6:.2f} MB')
    if '--check' in sys.argv and not check_math(cards):
        raise SystemExit('formula errors (see above)')


if __name__ == '__main__':
    main()
