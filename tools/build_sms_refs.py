"""Build the SMS manual page viewer data for SIRE Prep.

Reads the "SMS reference" text of every question (index.html, sire-data), finds each
referenced section in the SMS Finder index (SMSAPP/app/data/index.js), renders all pages
of those sections from the manual PDFs, and writes:

  sms/refs.js              window.SMS_REFS = {m: manuals, s: sections, r: parsed references}
  sms/<CODE>/<page>.webp   one image per PDF page

Run again after the manuals or the questions change:
  python tools/build_sms_refs.py [path-to-SMSAPP]        (default: the parent folder)
  python tools/build_sms_refs.py --dry                   (parse only, print the result)
  python tools/build_sms_refs.py --redo                  (render every page again, e.g. after changing WIDTH)
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'sms')
WIDTH = 1100          # rendered page width in pixels
QUALITY = 62          # WebP quality

# Manual codes as written in the references -> manual code in the SMS Finder index.
# None = a manual that is not in the SMS Finder (the reference stays plain text).
CODES = [
    (r'(?:CTM\s*/\s*OTM|OTM\s*/\s*CTM)\b', 'OTM'),
    (r'EMM\s*[-/]?\s*1(?![\d.])\s*[-/]?', 'EMM1'),     # EMM-1/8.1, EMM 1- 9.1.5, EMM/1- 13.1.6
    (r'EMM\s*[-/]?\s*2(?![\d.])\s*[-/]?', 'EMM2'),
    (r'EMM\b', 'EMM1'),
    (r'H\s*&\s*S\b', 'H&S'),
    (r'(?:PAM|NMM|TMM|OTM|ECM)\b', None),                 # same code
    (r'(?:CTM|GCM|FTM|LTM|MSMP|LMP|SSP|TM)\b', ''),        # not available
]
TOKEN = re.compile(
    '|'.join('(?P<c%d>%s)' % (i, p) for i, (p, _) in enumerate(CODES)) +
    r'|(?P<annex>ANNEX\s*-?\s*(?P<an>\d+)(?:\s?(?P<al>[A-N])(?![A-Za-z&]))?)'
    r'|(?P<num>\d+(?:\.\d+)+)'
    r'|(?P<to>\s*(?:-|\bTO\b)\s*(?=\d+\.\d))'
    r'|(?P<word>[A-Za-z]+)',
    re.I)


REDO = False


def load_index(smsapp):
    with open(os.path.join(smsapp, 'app', 'data', 'index.js'), encoding='utf-8') as f:
        txt = f.read()
    return json.loads(txt[txt.index('{'):txt.rstrip().rstrip(';').rindex('}') + 1])


class Resolver:
    def __init__(self, data):
        self.man = {m['code']: m for m in data['manuals']}
        self.pages, self.text = {}, {}
        for p in data['pages']:
            self.pages.setdefault(p['s'], []).append(p['p'])
            self.text[(p['m'], p['p'])] = p['t']
        self.secs = {}  # (code, num) -> [section]
        for s in data['sections']:
            if s['num']:
                self.secs.setdefault((s['m'], s['num'].upper()), []).append(s)

    def find(self, code, num):
        """-> (key, [sections], start page) or None"""
        num = num.upper()
        hit = self.secs.get((code, num))
        if hit:
            return num, hit, None
        parts = num.split('.')
        if len(parts) == 2 and parts[1] == '0':      # 9.0 = the whole chapter
            ch = [s for (c, n), ss in sorted(self.secs.items(), key=lambda kv: kv[1][0]['p'])
                  if c == code and n.split('.')[0] == parts[0] for s in ss]
            return (parts[0], ch, None) if ch else None
        for k in range(len(parts) - 1, 1, -1):      # 16.2.11 -> section 16.2, open at 16.2.11
            base = '.'.join(parts[:k])
            hit = self.secs.get((code, base))
            if hit:
                start = None
                for s in hit:
                    for sub in s['subs']:
                        if sub['num'] == num and start is None:
                            start = sub['page']
                if start is None:                    # look for the number at the start of a line
                    pat = re.compile(r'(?:^|\n)' + re.escape(num) + r'\.?(?:\s|$)')
                    for s in hit:
                        for pg in self.pages.get(s['id'], []):
                            if start is None and pat.search(self.text.get((code, pg), '')):
                                start = pg
                return base, hit, start
        return None

    def section_range(self, code, a, b):
        """ECM 4.1 - 4.12 -> every section from 4.1 to 4.12 (same chapter)."""
        pa, pb = a.split('.'), b.split('.')
        if len(pa) != 2 or len(pb) != 2 or pa[0] != pb[0] or int(pa[1]) >= int(pb[1]):
            return None
        out = []
        for i in range(int(pa[1]), int(pb[1]) + 1):
            out += self.secs.get((code, '%s.%d' % (pa[0], i)), [])
        return out or None


def parse(text, R):
    """Split a reference into plain text and links.
    -> list of str | {'x': link text, 'k': [section keys], 'at': start page or None}"""
    segs = []
    st = {'pos': 0, 'ctx': None, 'code': '', 'to': '', 'last': None}

    def plain(t):
        if t:
            if segs and isinstance(segs[-1], str):
                segs[-1] += t
            else:
                segs.append(t)

    def flush():
        plain(st['code'] + st['to'])
        st['code'] = st['to'] = ''

    def order(code, secs):
        keys = {}
        for s in secs:
            keys.setdefault(code + '|' + s['num'].upper(), s['p'])
        return sorted(keys, key=keys.get)

    for m in TOKEN.finditer(text):
        kind = m.lastgroup
        gap, tok = text[st['pos']:m.start()], m.group(0)
        st['pos'] = m.end()
        if kind.startswith('c'):
            flush()
            plain(gap)
            target = CODES[int(kind[1:])][1]
            if target is None:
                target = tok.upper()
            st['ctx'] = target if target in R.man else None
            st['code'] = tok if st['ctx'] else ''
            if not st['ctx']:
                plain(tok)
            st['last'] = None
            continue
        if kind == 'word':
            flush()
            plain(gap + tok)
            if tok.upper() != 'AND':
                st['ctx'] = st['last'] = None
            continue
        if kind == 'to':
            if st['last'] is None:          # "PAM-16.2": just a separator, keep it in the next gap
                st['pos'] = m.start()
                continue
            if not st['to']:
                plain(gap)
                st['to'] = tok
            else:
                flush()
                plain(gap + tok)
            continue
        # a section number or an annex
        code = st['ctx']
        num = m.group('num') or ('ANNEX %s%s' % (m.group('an'), (m.group('al') or '').upper()))
        if code and st['to'] and m.group('num'):            # "4.1 - 4.12", "9.1 TO 9.6"
            link = segs[st['last']]
            rng = R.section_range(code, link['n'], num)
            if rng and not gap:
                link['x'] += st['to'] + tok
                link['k'], link['at'], st['to'], st['last'] = order(code, rng), None, '', None
                continue
        res = R.find(code, num) if code else None
        if not res:
            flush()
            plain(gap + tok)
            st['last'] = None
            continue
        plain(st['to'])
        st['to'] = ''
        key, secs, start = res
        label = (st['code'] + gap + tok) if st['code'] else tok
        if not st['code']:
            plain(gap)
        st['code'] = ''
        segs.append({'x': label, 'k': order(code, secs), 'at': start, 'n': num})
        st['last'] = len(segs) - 1
    flush()
    plain(text[st['pos']:])
    return segs


def numbered_headings(doc, pages):
    """Subsection numbers (5.3.19) are small images left of the bold heading text, so they
    are not in the text layer. Return the page of every numbered heading, in order."""
    out = []
    for pg in pages:
        p = doc[pg - 1]
        rects = [r for im in p.get_images() for r in p.get_image_rects(im[0])
                 if r.x0 < 90 and r.width < 60 and r.height < 16 and r.y0 > 60]
        if not rects:
            continue
        for b in p.get_text('dict')['blocks']:
            for ln in b.get('lines', []):
                if not ''.join(s['text'] for s in ln['spans']).strip() or not ln['spans'][0]['flags'] & 16:
                    continue
                y = (ln['bbox'][1] + ln['bbox'][3]) / 2
                if any(r.y0 - 3 <= y <= r.y1 + 3 and r.x1 < ln['bbox'][0] for r in rects):
                    out.append(pg)
    return out


def build(smsapp, R, parsed, used):
    import fitz
    from PIL import Image

    docs = {}

    def doc(code):
        if code not in docs:
            docs[code] = fitz.open(os.path.join(smsapp, R.man[code]['file']))
        return docs[code]

    def folder(code):
        return re.sub(r'[^A-Za-z0-9]', '', code)

    def sec_pages(key):
        code, num = key.split('|')
        return sorted(pg for s in R.secs[(code, num)] for pg in R.pages.get(s['id'], []))

    # open subsection references (H&S 5.3.19) at the page of their numbered heading
    heads = {}
    for segs in parsed.values():
        for s in segs:
            if not isinstance(s, dict) or s['at'] or len(s['k']) != 1 or s['n'].count('.') != 2:
                continue
            key = s['k'][0]
            if key not in heads:
                heads[key] = numbered_headings(doc(key.split('|')[0]), sec_pages(key))
            i = int(s['n'].split('.')[2])
            if key.split('|')[1] == s['n'].rsplit('.', 1)[0] and 0 < i <= len(heads[key]):
                s['at'] = heads[key][i - 1]

    # render every page of every linked section
    sections, keep, made = {}, set(), 0
    for key in used:
        code, num = key.split('|')
        first = R.secs[(code, num)][0]
        pages = []
        for pg in sec_pages(key):
            rel = '%s/%d.webp' % (folder(code), pg)
            path = os.path.join(OUT, rel)
            keep.add(os.path.normpath(path))
            if os.path.exists(path) and not REDO:
                with Image.open(path) as im:
                    w, h = im.size
            else:
                page = doc(code)[pg - 1]
                z = WIDTH / page.rect.width
                pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
                im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                im.save(path, 'WEBP', quality=QUALITY, method=6)
                w, h = im.size
                made += 1
            pages.append([pg, w, h, os.path.getsize(path)])
        sections[key] = {'t': first['title'], 'p': pages, 'rev': first['rev'], 'date': first['date']}

    removed = 0
    for dirpath, _, files in os.walk(OUT):
        for f in files:
            path = os.path.normpath(os.path.join(dirpath, f))
            if f.endswith('.webp') and path not in keep:
                os.remove(path)
                removed += 1

    manuals = {}
    for key in used:
        code = key.split('|')[0]
        m = R.man[code]
        manuals[code] = {'t': m['title'], 'd': folder(code), 'rev': m['rev'], 'date': m['date']}
    refs = {r: [s if isinstance(s, str) else [s['x'], s['k'], s['at']] for s in segs]
            for r, segs in parsed.items()}
    data = {'m': manuals, 's': sections, 'r': refs}
    with open(os.path.join(OUT, 'refs.js'), 'w', encoding='utf-8') as f:
        f.write('/* Generated by tools/build_sms_refs.py - do not edit. */\nwindow.SMS_REFS=')
        f.write(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
        f.write(';\n')
    total = sum(len(s['p']) for s in sections.values())
    print('%d references, %d sections, %d pages (%d new, %d removed)' % (len(refs), len(sections), total, made, removed))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    global REDO
    dry = '--dry' in sys.argv
    REDO = '--redo' in sys.argv
    smsapp = os.path.abspath(args[0] if args else os.path.join(ROOT, '..'))
    R = Resolver(load_index(smsapp))

    with open(os.path.join(ROOT, 'index.html'), encoding='utf-8') as f:
        page = f.read()
    m = re.search(r'<script id="sire-data" type="application/json">(.*?)</script>', page, re.S)
    G = json.loads(m.group(1))['g']
    refs = sorted({g['s'] for g in G.values() if g.get('s')})

    parsed = {r: parse(r, R) for r in refs}
    used = sorted({k for segs in parsed.values() for s in segs if isinstance(s, dict) for k in s['k']})
    if dry:
        for r in refs:
            print(''.join('[%s%s]' % (s['x'], '@%s' % s['at'] if s['at'] else '') if isinstance(s, dict) else s for s in parsed[r]))
        npg = sum(len(R.pages[s['id']]) for k in used for s in R.secs[tuple(k.split('|'))])
        print('\n%d references, %d linked sections, %d pages' % (len(refs), len(used), npg))
        return
    build(smsapp, R, parsed, used)


if __name__ == '__main__':
    main()
