#!/usr/bin/env python3
"""Regenerate bank.tex, booklet.tex, solutions.tex and catalog.md from the question files under questions/.

Every question file starts with a comment header:

    % id:       seq-012
    % topic:    סדרות
    % subtopic: חישוב גבולות של סדרות
    % solution: full | partial | none
    % verified: no                     (only while a solution still awaits review)
    % suggested: yes                   (a proposed question, wrapped in the pink suggested environment;
                                        it goes into bank.tex only, not into the booklet or the site)

followed by the question body (without a leading \\item) and its solbox blocks.

This repository is public. The source of each question (sheet, semester) and the staff notes are kept
in the course's private repository (exercises/metadata.md), not in the question files. The suggested
questions are kept there too, under exercises/suggested/, until they are approved.

Usage:  python3 make_bank.py
        python3 make_bank.py --with-suggested ../lectureNotes9921/exercises/suggested
            # writes bank-preview.tex (not tracked by git): the bank together with the suggested questions.
            # booklet.tex, solutions.tex and catalog.md are not touched.
"""
import glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIELDS = ('id', 'topic', 'subtopic', 'solution', 'verified', 'suggested')
SOL_HE = {'full': 'מלא', 'partial': 'חלקי', 'none': 'אין'}


def read_question(path):
    meta, body = {}, []
    with open(path, encoding='utf-8') as f:
        for line in f:
            m = re.match(r'%\s*(\w+):\s*(.*)', line)
            if m and not body:
                # header fields this repo does not use (source, file, note in the private copies) are skipped
                if m.group(1) in FIELDS:
                    meta[m.group(1)] = m.group(2).strip()
            elif re.match(r'%\s*=+\s*$', line) and not body:
                continue
            else:
                body.append(line)
    meta['body'] = ''.join(body)
    meta['path'] = os.path.relpath(path, HERE).replace(os.sep, '/')
    meta['folder'] = os.path.basename(os.path.dirname(path))
    return meta


def preview(body, n=70):
    t = re.sub(r'\\begin\{solbox\}.*?\\end\{solbox\}', ' ', body, flags=re.S)
    t = re.sub(r'(?m)%.*$', '', t)
    t = re.sub(r'\\hint\{[^\n]*\}\s*$', ' ', t, flags=re.M)
    t = re.sub(r'\\(begin|end)\{[a-z*]+\}|\\bE|\\eE|\\item|\\textbf|\\ds\b|\\displaystyle', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return (t[:n] + '…') if len(t) > n else t


def suggested_dir():
    """The folder given after --with-suggested on the command line, or None."""
    if '--with-suggested' not in sys.argv:
        return None
    i = sys.argv.index('--with-suggested') + 1
    if i >= len(sys.argv) or not os.path.isdir(sys.argv[i]):
        raise SystemExit('--with-suggested needs the folder of the suggested questions, '
                         'e.g. ../lectureNotes9921/exercises/suggested')
    return os.path.abspath(sys.argv[i])


def load(extra=None):
    """The questions under questions/, and those under the folder extra (same layout) if given."""
    paths = glob.glob(os.path.join(HERE, 'questions', '*', '*.tex'))
    if extra:
        paths += glob.glob(os.path.join(extra, '*', '*.tex'))
    qs = [read_question(p) for p in sorted(paths)]
    qs.sort(key=lambda q: (q['folder'], q['id']))
    return qs


def chapter_body(qs, item, subsections=True, lists=True, first_page=True):
    r"""\section per chapter, \subsection per subtopic (unless subsections=False, lists=False);
    question numbers run continuously from the first question to the last.
    lists=False: no enumerate around the questions (item() numbers them itself)."""
    out, topic, sub = [], None, None
    for q in qs:
        new_topic = q['topic'] != topic
        new_sub = new_topic or (subsections and q['subtopic'] != sub)
        if new_sub and sub is not None and lists:
            out.append(r'\end{enumerate}')
        head = ''
        if new_topic:
            # a new chapter goes on in the same page; the heading is kept with what follows it
            first = topic is None and first_page
            topic = q['topic']
            head = '\\section{' + topic + '}'
            if lists:
                out.append('\n' + ('\\newpage\n' if first else '\\needspace{12\\baselineskip}\n') + head)
            else:
                out.append('\n\\newpage' if first else '')
        if new_sub:
            opt = '[resume]' if sub is not None else ''
            sub = q['subtopic']
            # David CLM has no Greek glyphs -- typeset them in math mode
            title = sub.replace('ε', r'$\varepsilon$').replace('δ', r'$\delta$')
            out.append(('\\subsection{' + title + '}\n' if subsections else '') + ('\\begin{enumerate}' + opt if lists else ''))
        out.append(item(q, '' if lists else head))
    if sub is not None and lists:
        out.append(r'\end{enumerate}')
    return out


RELEASE_LINE = '---'     # in structure.txt: the chapters below this line are not yet released to students


def load_structure():
    """structure.txt -> {subtopic: (chapter index, subtopic index, chapter name)}"""
    order, chapter, ci = {}, None, -1
    with open(os.path.join(HERE, 'structure.txt'), encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line == RELEASE_LINE:
                continue
            if line.startswith('## '):
                chapter, ci = line[3:].strip(), ci + 1
            elif line and not line.startswith('#'):
                order[line] = (ci, len(order), chapter)
    return order


def unreleased():
    """The subtopics below the release line in structure.txt. They stay out of the student booklets
    and the site (but not out of the preview with --with-suggested, or the review page)."""
    hidden, below = set(), False
    with open(os.path.join(HERE, 'structure.txt'), encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line == RELEASE_LINE:
                below = True
            elif below and line and not line.startswith('#'):
                hidden.add(line)
    return hidden


def write_bank(qs, target='bank.tex'):
    out = [r'''% קובץ זה נוצר אוטומטית ע"י make_bank.py -- אל תערכו אותו ידנית.
% להסתרת הפתרונות: החליפו את \soltrue ב-\solfalse.
\newif\ifsol
\soltrue
\documentclass[12pt, a4paper]{article}
\usepackage[most]{tcolorbox}   % חייב להיטען לפני ה-preamble (bidi)
\input{preamble/MotkePreamble}
\input{bank-setup}

\begin{document}
\selectlanguage{hebrew}
\begin{center}
{\LARGE\bf מאגר שאלות -- הסתברות לסטטיסטיקה (9921)}\\[0.5em]
{\large ''' + str(len(qs)) + r''' שאלות \ifsol -- עם פתרונות\fi}
\end{center}
\noindent{\small\color{gray}משמאל לכל שאלה מופיע שם הקובץ שלה, שבו משתמשים כדי לשלב אותה בדף תרגילים חדש.
החלק הראשון של השם הוא שם התיקייה שבה הקובץ נמצא, והוא לא תמיד תואם לפרק שבו השאלה מופיעה.\par}
\bigskip
{\small\tableofcontents}
''']
    out += chapter_body(qs, lambda q, head: '\\bankq{%s}{%s}' % (q['id'], q['path'][:-4]))
    out.append('\n\\end{document}\n')
    with open(os.path.join(HERE, target), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))


BOOKLET_HEAD = r'''% קובץ זה נוצר אוטומטית ע"י make_bank.py -- אל תערכו אותו ידנית.
% עמוד השער (סמסטר, שם הקורס, הערה): booklet-header.tex
\newif\ifsol
\solfalse
\documentclass[12pt, a4paper]{article}
\usepackage[most]{tcolorbox}   % חייב להיטען לפני ה-preamble (bidi)
\input{preamble/MotkePreamble}
\input{bank-setup}
%__SITENOTE__
\input{booklet-header}

\begin{document}
\selectlanguage{hebrew}
\booklettitlepage
{\small\tableofcontents}
'''


def qref_defs(qs):
    r"""In the student booklets \qref{id} prints the referred exercise's booklet number instead of its id."""
    out = ['\\expandafter\\def\\csname qref@%s\\endcsname{%d}' % (q['id'], n) for n, q in enumerate(qs, 1)]
    out.append(r'\renewcommand{\qref}[1]{\ifcsname qref@#1\endcsname\csname qref@#1\endcsname\else\textenglish{#1}\fi}')
    return out


def write_booklet(qs):
    """Student booklet: questions only -- no solutions, ids, sources or subtopic headings.
    Suggested questions stay out until they are approved."""
    qs = [q for q in qs if q.get('suggested') != 'yes']
    out = [BOOKLET_HEAD.replace('%__SITENOTE__', '' if has_hints(qs) else SITENOTE_NOHINTS)] + qref_defs(qs)
    out += chapter_body(qs, lambda q, head: '\\bookq[%s]{%s}' % (head, q['path'][:-4]), subsections=False, lists=False)
    out.append('\n\\end{document}\n')
    with open(os.path.join(HERE, 'booklet.tex'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))


# Part labels as in the PDF lists (Hebrew numerals): א..ט, י, יא, יב, ...
LETTERS = list('אבגדהוזחט') + ['י', 'יא', 'יב', 'יג', 'יד', 'טו', 'טז', 'יז', 'יח', 'יט', 'כ', 'כא', 'כב']
HINT_TOK = re.compile(r'\\begin\{(enumerate|itemize)\}|\\end\{(enumerate|itemize)\}|\\bE\b|\\eE\b|\\bit\b|\\eit\b|\\item\b|\\hint\{')


def hints_of(body):
    """[(part letter or '', hint LaTeX)] in order; the letter is the item of the top-level enumerate the hint sits in."""
    s = re.sub(r'(?m)(?<!\\)%.*$', '', body)
    out, stack, item = [], [], -1
    for m in HINT_TOK.finditer(s):
        t = m.group(0)
        if t in ('\\bE', '\\bit') or t.startswith('\\begin'):
            stack.append('enumerate' if t == '\\bE' or m.group(1) == 'enumerate' else 'itemize')
        elif t in ('\\eE', '\\eit') or t.startswith('\\end'):
            stack.pop()
        elif t == '\\item':
            if stack == ['enumerate']:
                item += 1
        else:                                   # \hint{ -- read the balanced argument
            i, level = m.end(), 1
            while level:
                level += {'{': 1, '}': -1}.get(s[i], 0) if s[i - 1] != '\\' else 0
                i += 1
            inside = bool(stack) and stack[0] == 'enumerate' and item >= 0
            out.append((LETTERS[item] if inside else '', s[m.end():i - 1]))
    return out


SOLUTIONS_HEAD = r'''% קובץ זה נוצר אוטומטית ע"י make_bank.py -- אל תערכו אותו ידנית.
% חוברת הרמזים והפתרונות לסטודנטים: רמזים (בלי פתרונות), ואחריהם התרגילים עם הפתרונות.
% מספרי התרגילים זהים למספרים בחוברת התרגילים (booklet.tex).
\newif\ifsol
\soltrue
\documentclass[12pt, a4paper]{article}
\usepackage[most]{tcolorbox}   % חייב להיטען לפני ה-preamble (bidi)
\input{preamble/MotkePreamble}
\input{bank-setup}
%__KIND__
\input{booklet-header}
% פתרון שעדיין לא נבדק מסומן כך, כמו באתר
\renewcommand{\unverified}{{\color{bkgray}\small\textbf{פתרון שלא נבדק על ידי צוות הקורס}}\par}

\begin{document}
\selectlanguage{hebrew}
\booklettitlepage
{\small\tableofcontents}
'''


# While no exercise has a hint yet, the booklets speak of solutions only.
KIND_HINTS = r'''\newcommand{\bookletkind}{רמזים ופתרונות}
\newcommand{\bookletsitenote}{באתר התרגול הרמזים והפתרונות נפתחים בלחיצה, שלב אחר שלב.}'''
KIND_NOHINTS = r'''\newcommand{\bookletkind}{פתרונות}
\newcommand{\bookletsitenote}{באתר התרגול הפתרונות נפתחים בלחיצה, שלב אחר שלב.}'''
SITENOTE_NOHINTS = r'''\newcommand{\bookletsitenote}{פתרונות מלאים, שנפתחים שלב אחר שלב, נמצאים באתר התרגול.
אפשר גם להוריד משם את חוברת הפתרונות.}'''


def has_hints(qs):
    return any(hints_of(q['body']) for q in qs)


def write_solutions(qs):
    """Hints and solutions booklet: part 1 lists the hints by exercise number, part 2 repeats every
    exercise with its solution. Numbering and order follow the student booklet."""
    qs = [q for q in qs if q.get('suggested') != 'yes']
    hints = has_hints(qs)
    out = [SOLUTIONS_HEAD.replace('%__KIND__', KIND_HINTS if hints else KIND_NOHINTS)] + qref_defs(qs)
    if hints:
        out += ['\n\\newpage\n\\section*{רמזים}\n\\addcontentsline{toc}{section}{רמזים}',
                'כאן מופיעים רק הרמזים, בלי הפתרונות. נסו קודם לפתור בעזרת הרמז, ורק אחר כך עברו לפתרון.\n']
    topic = None
    for n, q in enumerate(qs, 1):
        hs = hints_of(q['body'])
        if not hs:
            continue
        if q['topic'] != topic:
            topic = q['topic']
            out.append('\n\\subsection*{%s}' % topic)
        for letter, h in hs:
            label = '\\bknum{%d}' % n + ('\\ (%s)' % letter if letter else '')
            out.append('\\noindent %s\\enskip %s\\par\\smallskip' % (label, h))
    if hints:
        out.append('\n\\newpage\n\\section*{פתרונות}\n\\addcontentsline{toc}{section}{פתרונות}')
    out.append('\\renewcommand{\\hint}[1]{}   % the hints were listed above')
    out.append('\\setcounter{section}{0}')
    out += chapter_body(qs, lambda q, head: '\\bookq[%s]{%s}' % (head, q['path'][:-4]), subsections=False, lists=False, first_page=False)
    out.append('\n\\end{document}\n')
    with open(os.path.join(HERE, 'solutions.tex'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))


def write_catalog(qs):
    lines = ['# קטלוג מאגר השאלות', '',
             'נוצר אוטומטית ע"י `make_bank.py`. סה"כ **%d** שאלות.' % len(qs), '']
    pending = [q for q in qs if q.get('verified') == 'no']
    suggested = [q for q in qs if q.get('suggested') == 'yes']
    if suggested:
        lines += ['**הצעות חדשות שטרם אושרו (%d, בתיבה ורודה, רק במאגר):** ' % len(suggested) +
                  ', '.join(f"[{q['id']}]({q['path']})" for q in suggested), '']
    if pending:
        lines += ['**פתרונות שטרם נבדקו (%d):** ' % len(pending) +
                  ', '.join(f"[{q['id']}]({q['path']})" for q in pending), '']
    topic = None
    for q in qs:
        if q['topic'] != topic:
            topic = q['topic']
            n = sum(1 for x in qs if x['topic'] == topic)
            lines += ['', f'## {topic} ({n})', '',
                      '| מזהה | תת־נושא | פתרון | התחלת השאלה |',
                      '|---|---|---|---|']
        p = preview(q['body']).replace('|', '\\|')
        sol = SOL_HE.get(q.get('solution', ''), q.get('solution', ''))
        if q.get('verified') == 'no':
            sol += ' ⚠️ טרם נבדק'
        if q.get('suggested') == 'yes':
            sol += ' 🌸 הצעה'
        lines.append(f"| [{q['id']}]({q['path']}) | {q['subtopic']} | {sol} | {p} |")
    with open(os.path.join(HERE, 'catalog.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    extra = suggested_dir()
    qs = load(extra)
    structure = load_structure()
    missing = sorted({q['subtopic'] for q in qs} - set(structure))
    if missing:
        raise SystemExit(f'subtopics missing from structure.txt: {missing}')
    for q in qs:
        q['topic'] = structure[q['subtopic']][2]      # the chapter comes from structure.txt
    qs.sort(key=lambda q: (structure[q['subtopic']][:2], q['id']))
    ids = [q['id'] for q in qs]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise SystemExit(f'duplicate ids: {sorted(dup)}')
    # with \solfalse the comment package only recognises \end{solbox} at the start of a line
    bad = [q['id'] for q in qs if re.search(r'(?m)^[ \t]+\\end\{solbox\}', q['body'])]
    if bad:
        raise SystemExit(f'indented \\end{{solbox}} (breaks \\solfalse) in: {bad}')
    if extra:
        write_bank(qs, 'bank-preview.tex')
        nsug = sum(1 for q in qs if q.get('suggested') == 'yes')
        raise SystemExit(f'{len(qs)} questions ({nsug} suggested) -> bank-preview.tex')
    hidden = unreleased()
    held = sum(1 for q in qs if q['subtopic'] in hidden)
    qs = [q for q in qs if q['subtopic'] not in hidden]
    if held:
        print(f'{held} questions below the release line in structure.txt (not released yet)')
    write_bank(qs)
    write_booklet(qs)
    write_solutions(qs)
    write_catalog(qs)
    pending = sum(1 for q in qs if q.get('verified') == 'no')
    nsug = sum(1 for q in qs if q.get('suggested') == 'yes')
    if nsug:
        print(f'{nsug} suggested questions (bank only)')
    print(f'{len(qs)} questions -> bank.tex, booklet.tex, solutions.tex, catalog.md'
          + (f'  ({pending} solutions not yet verified)' if pending else ''))
