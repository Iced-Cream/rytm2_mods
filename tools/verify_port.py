#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check an elemod port against rytm-mods' own build, label by label.

1. Re-assemble the original stub the way rytm-mods' tools/build.py does (its
   params as --defsym, sections placed at their registry caves, shared.inc from
   0000-shared re-assembled at its cave) and require the result to equal the
   T2 build's cave bytes - so the old symbol table is the T2 build's.
2. For every label of the original, disassemble its segment (to the next label)
   in T2 and in the new image, and replace every address by label+offset using
   each side's own symbol table (T2: the re-assembly; new: the link map). The
   normalised texts must match; differences are printed.

usage: verify_port.py ELEKLOADER RYTM_MODS_SRC MOD_DIR NEW_ID STOCK T2 NEW NEW_MAP INC

e.g. python3 -I tools/verify_port.py path/to/elekloader ../rytm-mods-src 0013-voice-dac voice-dac \
       STOCK.syx T2.syx r2-all.syx r2-all.syx.map.json include/ar2-1.73.inc
(T2: rytm-mods-src's default build; NEW and its .map.json: an elekloader.patch build with the port.
Reads both images locally and prints addresses, labels and instruction text only.)
"""
import json, re, subprocess, sys, tomllib, tempfile, os
from pathlib import Path

EL, SRC, MDIR, NEW_ID, STOCK, T2P, NEWP, MAPP, INC = sys.argv[1:10]
sys.path.insert(0, EL)
from elekloader import formats
st, dev, _ = formats.load(STOCK)
B = 0x40000400
S0 = formats.main_image(st, dev)
T2 = formats.main_image(formats.parse(T2P, dev), dev)
NI = formats.main_image(formats.parse(NEWP, dev), dev)
DDR, BLOB = 0x47be0000, B + len(S0) + 0x58
SRC = Path(SRC)
reg = tomllib.loads((SRC / "registry/allocations.toml").read_text())
sys.path.insert(0, str(SRC / "tools"))
import layout

def img_at(im, a, n):
    if DDR <= a < 0x47c00000:
        a = a - DDR + BLOB
    return bytes(im[a - B:a - B + n])

tmp = Path(tempfile.mkdtemp())
(tmp / "symbols.inc").write_text(Path(INC).read_text())

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        sys.exit("FAILED %s\n%s%s" % (" ".join(map(str, cmd)), p.stdout, p.stderr))
    return p.stdout

def assemble(mdir):
    mod = tomllib.loads((SRC / "mods" / mdir / "mod.toml").read_text())
    owner = mod["mod"]["id"]
    params = dict(mod.get("params", {}))
    claims = [c for c in reg["cave"] if c["owner"] == owner
              and not layout.gated_out(c.get("gate"), params, owner)]
    obj, elf = tmp / (mdir + ".o"), tmp / (mdir + ".elf")
    defs = []
    for k, v in sorted(params.items()):
        defs += ["--defsym", "P_%s=%d" % (k.upper(), int(v))]
    run(["m68k-linux-gnu-as", "-mcpu=5475", "-I", str(tmp), "-I", str(SRC), *defs, "-o", str(obj),
         str(SRC / "mods" / mdir / mod["sources"]["stub"])])
    placed = ["--section-start=%s=0x%08x" % (c.get("section", ".text"), c["addr"]) for c in claims]
    run(["m68k-linux-gnu-ld", "-e", "0", *placed, "-o", str(elf), str(obj)])
    secs = {}
    for c in claims:
        name = c.get("section", ".text")
        binf = tmp / ("%s%s.bin" % (mdir, name.replace(".", "_")))
        run(["m68k-linux-gnu-objcopy", "-O", "binary", "--only-section", name, str(elf), str(binf)])
        secs[name] = (c["addr"], binf.read_bytes())
    syms = {}
    for line in run(["m68k-linux-gnu-nm", "-n", str(elf)]).splitlines():
        p = line.split()
        if len(p) == 3 and p[1] in "tTdDbBrR":
            syms[p[2]] = int(p[0], 16)
    return secs, syms

# 0000-shared first, for shared.inc
sh_secs, sh_syms = assemble("0000-shared")
for name, (a, b) in sh_secs.items():
    assert img_at(T2, a, len(b)) == b, "0000-shared does not re-assemble to T2's bytes"
(tmp / "shared.inc").write_text("".join("        .equ %s, 0x%08x\n" % (k, v)
                                        for k, v in sh_syms.items() if k.startswith("shared_")))
secs, old = assemble(MDIR)
for name, (a, b) in secs.items():
    got = img_at(T2, a, len(b))
    if got != b:
        sys.exit("%s %s: re-assembly differs from T2 at 0x%08x" % (MDIR, name, a))
print("re-assembly of %s equals the T2 build's caves: %s" % (
    MDIR, ", ".join("%s 0x%08x+%d" % (n, a, len(b)) for n, (a, b) in secs.items())))

mp = json.loads(Path(MAPP).read_text())
new = {k.split(":", 1)[1]: int(v, 16) for k, v in mp.items()
       if k.startswith(NEW_ID + ":") and DDR <= int(v, 16) < 0x47c00000}
# a global alias (the mod-id-prefixed name a site uses) sits on the original label's address
alias = {k for k in new if k.startswith(NEW_ID.replace("-", "_") + "_") and k not in old
         and any(new[j] == new[k] and j != k for j in new)}
for k in alias:
    del new[k]
# labels the hand ports renamed rather than aliased
for o, n in {"slice_menu_add": "slice_loop_menu_add", "amp_attack": "env_reset_amp_attack"}.items():
    if n in new and o not in new:
        new[o] = new.pop(n)
# the original's shared routines live in 0000-shared; this mod's own copy has the same labels
old_all = dict(old); old_all.update({k: v for k, v in sh_syms.items()})
ranges_old = [(a, a + len(b)) for a, b in secs.values()] + [(a, a + len(b)) for a, b in sh_secs.values()]
lo_new = min(new.values()); hi_new = max(new.values()) + 0x400

def namer(table, ranges):
    items = sorted((v, k) for k, v in table.items())
    def f(v):
        if not any(s <= v < e + 2 for s, e in ranges):
            return None
        best = None
        for a, k in items:
            if a <= v:
                best = (a, k)
            else:
                break
        return None if best is None else ("%s+%d" % (best[1], v - best[0]) if v != best[0] else best[1])
    return f
name_old = namer(old_all, ranges_old)
name_new = namer(new, [(lo_new, hi_new)])

def norm(lines, f, seg=None):
    idx = {a: i for i, (a, _) in enumerate(lines)}
    out = []
    for a0, ins in lines:
        ins = re.sub(r"%pc@\((0x[0-9a-f]+)\)", r"\1", ins)
        ins = re.sub(r"%pc@\((0x[0-9a-f]+),", r"(\1,", ins)
        def rep(m):
            v = int(m.group(0), 0) & 0xffffffff
            if v in idx and seg and seg[0] <= v < seg[1]:
                return "@%d" % idx[v]
            n = f(v)
            return n if n else m.group(0)
        ins = re.sub(r"0x[0-9a-f]+", rep, ins)
        ins = re.sub(r"#(-?\d{6,})", lambda m: "#" + (f(int(m.group(1)) & 0xffffffff) or m.group(1)), ins)
        ins = re.sub(r"^(b\w\w|bra|bsr)[swl]\b", r"\1", ins)
        out.append(ins)
    return out

def dis(b, vma):
    f = tmp / "seg.bin"
    f.write_bytes(b)
    o = run(["m68k-linux-gnu-objdump", "-D", "-b", "binary", "-m", "m68k:cfv4e",
             "--adjust-vma=0x%x" % vma, str(f)])
    r = []
    for line in o.splitlines():
        m = re.match(r"\s*[0-9a-f]+:\s+(?:[0-9a-f]{4} )+\s*(.*)", line)
        if m and not re.match(r"\s*[0-9a-f]+:", line): m = None
        if m:
            r.append((int(line.split(":")[0], 16), re.sub(r"\s+", " ", m.group(1)).strip()))
    return r

labels = sorted((v, k) for k, v in old.items() if any(s <= v < e for s, e in ranges_old[:len(secs)]))
bad = 0
for i, (a, k) in enumerate(labels):
    end = next((v for v, _ in labels[i + 1:] if v > a), None)
    sec_end = next(e for s, e in ranges_old if s <= a < e)
    end = min(end or sec_end, sec_end)
    if end <= a:
        continue
    if k not in new:
        print("  label %s missing in the new link" % k); bad += 1; continue
    ob = img_at(T2, a, end - a)
    # the new segment: to this label's successor in the new map
    nxt = sorted(v for v in new.values() if v > new[k])
    nend = nxt[0] if nxt else new[k] + (end - a) + 64
    nb = img_at(NI, new[k], nend - new[k])
    A, Bn = norm(dis(ob, a), name_old, (a, end)), norm(dis(nb, new[k]), name_new, (new[k], nend))
    Bn = Bn[:len(A)] if len(Bn) > len(A) and A == Bn[:len(A)] else Bn
    if A != Bn:
        # data: compare words, a pointer matching when both name the same label
        ok = len(ob) <= len(nb)
        i = 0
        while ok and i < len(ob):
            if ob[i] == nb[i]:
                i += 1; continue
            w = (i // 2) * 2
            found = False
            for o in (w - 2, w):
                if 0 <= o and o + 4 <= len(ob):
                    x = int.from_bytes(ob[o:o+4], "big"); y = int.from_bytes(nb[o:o+4], "big")
                    if name_old(x) and name_old(x) == name_new(y):
                        i = o + 4; found = True; break
            ok = found
        if ok:
            continue
        bad += 1
        print("  %s: %d vs %d instructions" % (k, len(A), len(Bn)))
        for x, y in zip(A, Bn):
            if x != y:
                print("     T2 %-50s new %s" % (x, y))
print("%s: %d labels compared, %d differ" % (NEW_ID, len(labels), bad))
