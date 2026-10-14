#!/usr/bin/env python3
"""Build the staff review page (review.html): every hint and solution, official or written by Claude,
with buttons to approve each one. The page itself is a private artifact on claude.ai; the marks are kept
in its own store (collection "reviews", one document per card id, e.g. "rv-003b").
The page: https://claude.ai/artifact/Ky9gjMS5mRAeExQERygKda

The page shows the source of each question and the suggested questions, so it needs a checkout of the
private repository next to this one. Nothing it writes goes into git.

Usage:  python3 tools/build_review.py ../lectureNotes9921 [out.html]      (default out: build/review.html)

From the private repository it reads:
  exercises/metadata.md          the source of each question
  exercises/suggested/           the suggested questions
  exercises/review-notes.json    per card: where Claude corrected or completed the solution sheet (shown
                                 as "check carefully" until the solution is approved)
  exercises/review-snapshot.json per card: the content the reviewer last saw, and the automatic check
                                 (pre, preReason, preFix). Updated with --snapshot (see below).

    python3 tools/build_review.py ../lectureNotes9921 --changed     lists the cards whose hint, text or
                                                                  solution differ from the snapshot
    python3 tools/build_review.py ../lectureNotes9921 --snapshot    stores the current content as the snapshot
"""
import glob, hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import make_site                                              # noqa: E402
from make_bank import load, load_structure, read_question    # noqa: E402


def sources(private):
    """{question id: source} from metadata.md and from the headers of the suggested questions."""
    out = {}
    for line in open(os.path.join(private, 'exercises', 'metadata.md'), encoding='utf-8'):
        cells = [c.strip() for c in re.split(r'(?<!\\)\|', line.strip())[1:-1]]
        if len(cells) >= 2 and re.match(r'^[a-z]+-\d+$', cells[0]):
            out[cells[0]] = cells[1].replace('\\|', '|')
    for p in glob.glob(os.path.join(private, 'exercises', 'suggested', '*', '*.tex')):
        m = re.search(r'(?m)^%\s*source:\s*(.*)$', open(p, encoding='utf-8').read())
        if m:
            out[os.path.basename(p)[:-4]] = m.group(1).strip()
    return out


def digest(item):
    """What the reviewer reads on a card; a mark is stale once this changes."""
    s = json.dumps([item['text'], item['hint'], item['steps']], ensure_ascii=False)
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def items(private):
    qs = load(os.path.join(private, 'exercises', 'suggested'))
    structure = load_structure()
    qs.sort(key=lambda q: (structure[q['subtopic']][:2], q['id']))
    book = {q['id']: n for n, q in enumerate((q for q in qs if q.get('suggested') != 'yes'), 1)}
    bank = {q['id']: n for n, q in enumerate(qs, 1)}
    refs = {q['id']: str(book[q['id']]) if q['id'] in book else 'מהצעה חדשה' for q in qs}
    cards = make_site.build_cards(qs, structure, refs)
    folder = {q['id']: q['folder'] for q in qs}
    src = sources(private)
    snap_path = os.path.join(private, 'exercises', 'review-snapshot.json')
    snap = json.load(open(snap_path, encoding='utf-8')) if os.path.exists(snap_path) else {}
    notes_path = os.path.join(private, 'exercises', 'review-notes.json')
    notes = json.load(open(notes_path, encoding='utf-8')) if os.path.exists(notes_path) else {}
    out = []
    for c in cards:
        suffix = c['id'][len(c['qid']):]
        letter = make_site.LETTERS[make_site.LATIN.index(suffix)] if suffix else ''
        sugg = c['qid'] not in book
        it = {
            'id': c['id'], 'qid': c['qid'], 'topic': c['topic'], 'sub': c['sub'],
            'text': c['text'], 'hint': c.get('hint', ''),
            'steps': (c['solution'] or {}).get('steps', []),
            'official': bool(c['solution'] and c['solution'].get('official')),
            'number': f'{bank[c["qid"]]}{letter} במאגר' if sugg else f'{book[c["qid"]]}{letter}',
            'source': '' if sugg else src.get(c['qid'], ''), 'generalNote': '',
            'pre': '', 'preReason': '', 'preFix': '',
        }
        if sugg:
            it['suggested'] = True
            why = make_site.convert(src.get(c['qid'], ''), make_site.Ctx(c['qid']), refs)
            it['where'] = (why + f'<br><span class="qid" dir="ltr">exercises/suggested/'
                           f'{folder[c["qid"]]}/{c["qid"]}.tex</span>')
        old = snap.get(c['id'])
        if old and old.get('digest') == digest(it):   # the automatic check still describes this content
            it.update({k: old.get(k, '') for k in ('pre', 'preReason', 'preFix')})
        if c['id'] in notes and not it['official']:   # Claude corrected or completed the solution sheet here
            it['pre'] = 'check'
            it['preReason'] = '<br>'.join(make_site.convert(n, make_site.Ctx(c['qid']), refs) for n in notes[c['id']])
        out.append(it)
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        raise SystemExit(__doc__)
    private = os.path.abspath(args[0])
    its = items(private)
    snap_path = os.path.join(private, 'exercises', 'review-snapshot.json')
    if '--changed' in sys.argv or '--snapshot' in sys.argv:
        snap = json.load(open(snap_path, encoding='utf-8')) if os.path.exists(snap_path) else {}
        changed = [it['id'] for it in its if it['id'] in snap and snap[it['id']].get('digest') != digest(it)]
        if '--changed' in sys.argv:
            print('\n'.join(changed))
            return
        for it in its:
            prev = snap.get(it['id'], {})
            keep = {k: prev.get(k, '') for k in ('pre', 'preReason', 'preFix')} if prev.get('digest') == digest(it) else {}
            snap[it['id']] = {'digest': digest(it), **keep}
        for k in [k for k in snap if k not in {it['id'] for it in its}]:
            del snap[k]
        json.dump(snap, open(snap_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        print(f'snapshot: {len(snap)} cards ({len(changed)} changed since the last one) -> {snap_path}')
        return
    topics = []
    for it in its:
        if it['topic'] not in topics:
            topics.append(it['topic'])
    data = json.dumps({'items': its, 'topics': topics}, ensure_ascii=False, separators=(',', ':'))
    data = data.replace('</', '<\\/')
    tpl = open(os.path.join(HERE, 'tools', 'review-template.html'), encoding='utf-8').read()
    target = args[1] if len(args) > 1 else os.path.join(HERE, 'build', 'review.html')
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    macros = open(os.path.join(HERE, 'site', 'macros.json'), encoding='utf-8').read()
    open(target, 'w', encoding='utf-8').write(tpl.replace('/*__DATA__*/', data).replace('/*__MACROS__*/', macros))
    n_sugg = sum(1 for it in its if it.get('suggested'))
    print(f'{target}: {len(its)} cards ({len(its) - n_sugg} in the booklet, {n_sugg} suggested)')


if __name__ == '__main__':
    main()
