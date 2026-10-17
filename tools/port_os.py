#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Port every mod here from OS 1.73 to OS 1.74, mechanically.

    PYTHONPATH=$EL python3 tools/port_os.py STOCK_1.73 STOCK_1.74

Needs elekloader importable (its ColdFire decoder and file reader). Writes:

- include/ar2-1.74.inc: include/ar2-1.73.inc with every address moved;
- <mod>/os1.74/<source>: each source of the mod with its include line and
  every firmware address in its code moved (comments are left alone);
- the "1.74" entry of each mod.json's "ports": those sources, and the sites
  with their addresses moved and their stock bytes read from 1.74.

1.73 stays the source of truth: change a 1.73 source, then run this again.

How an address moves. 1.74's main OS is 1.73's with code added in two
places (Outbox 8's main-output routing): the code after 0x4005702a sits
0x6c further on, after 0x40123e2a 0x1cc, and the data after the code by
other amounts. RAM from 0x402ce000 on (what the OS clears at start, and
everything past the image) and the SRAM are where they were. So:

- code: the 1.73 address + the shift of its region, accepted only if the
  next ten instructions there are 1.73's (opcodes and operands equal, but
  for 32-bit addresses into the image);
- data: what the code that names the address in 1.73 names in 1.74 (every
  instruction operand equal to it, each instruction moved as code is), or
  failing that, the address's own bytes found once nearby. Where both give
  an answer they must agree. Inside a table, where neither is unique: the
  shift of the nearest bytes found once, if the 32 bytes around the address
  are the same at the shifted address (but for addresses);
- an address no rule gives is an error, named, and nothing is written.

Only addresses, and stock instruction bytes at the sites, are written: no
other firmware bytes.
"""
import collections
import json
import re
import sys
from pathlib import Path

from elekloader import formats, syx
from elekloader.isa import coldfire as cf

ROOT = Path(__file__).resolve().parent.parent
B = 0x40000400
BSS = 0x402CE000                 # the OS clears from here at start, in both
CODE_END = 0x401B5000            # past the last instruction moved as code
INSERTS = [(0x4005702A, 0x40057060), (0x40123E2A, 0x40123E60)]   # 1.73 ranges that changed
SHIFTS = [0, 0x6C, 0x1CC]
HEX = re.compile(r'\b0x([0-9a-fA-F]{8})\b')
# Where an inferred region starts: no instruction starts there to match, so
# its region's shift (audio_dsp_region, which no mod uses).
REGIONS = {0x40100000: 0x40100000 + 0x6C}
MAIN = {'1.73': '28d9ef40c895e03f17dfce096543109adaf708947392db72818fc2a412d685d6',
        '1.74': '34cd0c4da8e4b810d1b25284475a99ea53821e2ab7d30a978bf15dc578251f3b'}


class Mapper:
    def __init__(self, old, new):
        self.a, self.b = old, new
        self.ra, self.rb = cf.reader(old, B), cf.reader(new, B)
        self._refs = None

    def img(self, v):
        return B <= v < BSS

    def insns(self, img, rd, at, n):
        out = []
        for _ in range(n):
            i = cf.decode(rd(at), at)
            out.append(bytes(img[at - B:at - B + i.length]))
            if i.flags & cf.ILLEGAL or i.op in ('rts', 'rte'):
                break
            at += i.length
        return out

    def same(self, x, y):
        """Two instructions' bytes, equal but for 32-bit addresses into the image."""
        if len(x) != len(y) or x[:2] != y[:2]:
            return False
        for p in range(len(x)):
            if x[p] != y[p] and not any(
                    k + 4 <= len(x) and self.img(int.from_bytes(x[k:k + 4], 'big'))
                    and self.img(int.from_bytes(y[k:k + 4], 'big'))
                    for k in range(max(2, (p - 3) & ~1), p + 1, 2)):
                return False
        return True

    def code(self, at, n=10):
        if at < INSERTS[0][0]:
            ds = [0]
        elif at < INSERTS[0][1]:
            ds = [0, 0x6C]
        elif at < INSERTS[1][0]:
            ds = [0x6C]
        elif at < INSERTS[1][1]:
            ds = [0x6C, 0x1CC]
        else:
            ds = [0x1CC]
        p = self.insns(self.a, self.ra, at, n)
        for d in ds:
            q = self.insns(self.b, self.rb, at + d, n)
            if len(p) >= min(n, 3) and len(p) == len(q) and all(map(self.same, p, q)):
                return at + d
        return None

    def refs(self, v):
        if self._refs is None:
            self._refs = collections.defaultdict(list)
            pc = B
            while pc < CODE_END:
                i = cf.decode(self.ra(pc), pc)
                if not i.flags & cf.ILLEGAL and i.length >= 6:
                    for k in range(2, i.length - 2, 2):
                        self._refs[int.from_bytes(self.a[pc - B + k:pc - B + k + 4], 'big')].append((pc, k))
                pc += i.length
        got = collections.Counter()
        for pc, k in self._refs.get(v, []):
            m = self.code(pc)
            if m is not None:
                got[int.from_bytes(self.b[m - B + k:m - B + k + 4], 'big')] += 1
        return got

    def window(self, v, w=24):
        s = self.a[v - B:v - B + w]
        if len(set(s)) < 5:
            return None
        lo, hi = max(0, v - B - 0x800), v - B + 0x800
        i = self.b.find(s, lo, hi)
        if i < 0 or self.b.find(s, i + 1, hi) >= 0:
            return None
        return i + B

    def __call__(self, v, kind=None):
        """-> (1.74 address, how) or raises KeyError naming why."""
        if not (B <= v < BSS):
            if BSS <= v < B + len(self.a):
                r = self.refs(v)
                if r and set(r) != {v}:
                    raise KeyError('%#x: RAM the code names differently in 1.74: %s'
                                   % (v, {hex(k): c for k, c in r.items()}))
            return v, 'same'
        if v < CODE_END and kind != 'data':
            m = self.code(v)
            if m is not None:
                return m, 'code'
        r, w = self.refs(v), self.window(v)
        if r:
            (m, n), = r.most_common(1)
            if len(r) > 1 and n < 0.8 * sum(r.values()):
                raise KeyError('%#x: the code that names it disagrees: %s'
                               % (v, {hex(k): c for k, c in r.items()}))
            if w is not None and w != m:
                raise KeyError('%#x: named as %#x, its bytes at %#x' % (v, m, w))
            return m, 'refs'
        if w is not None:
            return w, 'bytes'
        n = self.near(v)
        if n is not None:
            return n, 'near'
        raise KeyError('%#x: no rule moves it' % v)

    def near(self, v, span=0x400):
        """Inside a table or a run of like bytes: the shift of the nearest bytes
        found once, if 32 bytes around v are the same there (but for addresses)."""
        for off in range(4, span, 4):
            for u in (v - off, v + off):
                w = self.window(u)
                if w is None:
                    continue
                d = w - u
                lo = max(B, v - 16)
                x = self.a[lo - B:v - B + 16]
                y = self.b[lo - B + d:v - B + 16 + d]
                if len(x) == len(y) and self.same(b'\0\0' + x, b'\0\0' + y):
                    return v + d
                return None
        return None


def code_part(line):
    """-> (code, comment): the comment starts at the first '|' outside a string."""
    q = False
    for i, c in enumerate(line):
        if c == '"':
            q = not q
        elif c == '|' and not q:
            return line[:i], line[i:]
    return line, ''


def port_source(text, M, errors, where):
    out = []
    for n, line in enumerate(text.split('\n'), 1):
        code, comment = code_part(line)
        code = code.replace('../include/ar2-1.73.inc', '../include/ar2-1.74.inc')

        def sub(m):
            v = int(m.group(1), 16)
            try:
                nv, _how = M(v)
            except KeyError as e:
                errors.append('%s:%d: %s' % (where, n, e))
                return m.group(0)
            return '0x%08x' % nv if nv != v else m.group(0)
        out.append(HEX.sub(sub, code) + comment)
    return '\n'.join(out)


def port_sites(sites, M, new, errors, where):
    out = []
    for s in sites:
        s = dict(s)
        a = int(s['addr'], 16)
        old = bytes.fromhex(s['stock'])
        try:
            na, _how = M(a, 'data' if s['op'] == 'ptr' else None)
        except KeyError as e:
            errors.append('%s: site %s: %s' % (where, s['addr'], e))
            continue
        got = bytes(new[na - B:na - B + len(old)])
        if s['op'] == 'ptr':
            want = M(int.from_bytes(old, 'big'))[0].to_bytes(4, 'big')
            if got != want:
                errors.append('%s: ptr site %s: 1.74 holds %s, not %s' % (where, s['addr'], got.hex(), want.hex()))
        elif not M.same(old, got) and old != got:
            # several instructions: compare them one by one
            p = M.insns(M.a, M.ra, a, 64)
            q = M.insns(M.b, M.rb, na, 64)
            k = n = 0
            ok = True
            while n < len(old) and k < len(p):
                ok = ok and k < len(q) and M.same(p[k], q[k])
                n += len(p[k])
                k += 1
            if not ok or n != len(old):
                errors.append('%s: site %s: 1.74 has %s where 1.73 has %s' % (where, s['addr'], got.hex(), old.hex()))
        if 'new' in s:
            nb = bytearray.fromhex(s['new'])
            for k in range(0, len(nb) - 3, 2):
                w = int.from_bytes(nb[k:k + 4], 'big')
                if B <= w < BSS and old[k:k + 4] == nb[k:k + 4]:
                    nb[k:k + 4] = got[k:k + 4]          # an operand kept from stock
                elif B <= w < BSS:
                    nb[k:k + 4] = M(w)[0].to_bytes(4, 'big')
            s['new'] = nb.hex()
        s['addr'] = '0x%08x' % na
        s['stock'] = got.hex()
        out.append(s)
    return out


def main(stock173, stock174):
    imgs = {}
    for p in (stock173, stock174):
        st, dev, rel = formats.load(p)
        img = formats.main_image(st, dev)
        if dev.key != 'analog-rytm-mk2' or rel.version not in MAIN or syx.sha(img) != MAIN[rel.version]:
            sys.exit('%s: not stock Analog Rytm MKII 1.73 or 1.74' % p)
        imgs[rel.version] = img
    M = Mapper(imgs['1.73'], imgs['1.74'])
    errors, writes = [], {}

    inc = (ROOT / 'include/ar2-1.73.inc').read_text()
    lines = []
    for line in inc.split('\n'):
        m = re.match(r'(\s+\.equ\s+\w+,\s+)0x([0-9a-f]{8})(\s+\|\s+(\w+),.*)', line)
        if m and m.group(4) != 'const':
            v = int(m.group(2), 16)
            try:
                nv, _ = M(v)
                line = '%s0x%08x%s' % (m.group(1), nv, m.group(3))
            except KeyError as e:
                if m.group(4) == 'data' and line.rstrip().endswith('inferred') and v in REGIONS:
                    line = '%s0x%08x%s' % (m.group(1), REGIONS[v], m.group(3))
                else:
                    errors.append('include: %s' % e)
        lines.append(line)
    text = '\n'.join(lines).replace('OS 1.73, main OS sha256 ' + MAIN['1.73'], 'OS 1.74, main OS sha256 ' + MAIN['1.74'])
    text = text.replace('from rytm-mods-src re/symbols.toml', 'from rytm-mods-src re/symbols.toml, moved to OS 1.74 by tools/port_os.py')
    writes[ROOT / 'include/ar2-1.74.inc'] = text

    for mj in sorted(ROOT.glob('*/mod.json')):
        mdir = mj.parent
        mod = json.loads(mj.read_text())
        srcs = []
        for s in mod['sources']:
            p = mdir / s
            writes[mdir / 'os1.74' / p.name] = port_source(p.read_text(), M, errors, '%s/%s' % (mdir.name, s))
            srcs.append('os1.74/' + p.name)
        sites = port_sites(mod['sites'], M, imgs['1.74'], errors, mdir.name)
        mod.setdefault('ports', {})['1.74'] = {'sources': srcs, 'sites': sites}
        writes[mj] = json.dumps(mod, indent=1) + '\n'

    if errors:
        sys.exit('\n'.join(errors) + '\n%d errors; nothing written' % len(errors))
    for p, t in writes.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, newline='\n')
    print('wrote %d files' % len(writes))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
