#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Port one rytm-mods-src mod to an elemod mod folder.

    PYTHONPATH=$EL python3 tools/port_mod.py RYTM_MODS_SRC MOD_DIR NEW_ID STOCK_SYX

e.g. PYTHONPATH=~/elekloader python3 tools/port_mod.py ../rytm-mods-src \
         0003-velocity-humanise velocity-humanise \
         /mnt/d/Development/Projects/ARMKII/Analog-Rytm_MKII_OS1.73.syx

Needs elekloader importable (PYTHONPATH pointing at an elekloader checkout) and
m68k-linux-gnu-objdump on PATH. Writes NEW_ID/NEW_ID.s and NEW_ID/mod.json;
the README is written by hand.

What it does, mechanically:

- Reads the mod's claims from registry/allocations.toml and keeps those its
  default params select (the same `gate` rules as rytm-mods' tools/layout.py).
- Source: symbols.inc -> ../include/ar2-1.73.inc; shared.inc -> the shared
  runtime included at the end of the unit; mods/<dir>/x.inc -> x.inc (copied);
  every `.section`/`.pushsection` -> `.text` (the elemod linker places one .run); each default
  param P_<NAME> becomes an `.equ`, as rytm-mods' build passed it.
- Every label a detour enters or a patch points at gets a `.globl` alias with
  the mod id's prefix (the label itself if it already has it); the stub keeps
  using its own local labels, so its code assembles as before.
- Sites:
    detour                      -> "jmp", stock = the whole displaced instructions
    patch, replace, code        -> "bytes" kind code, widened to whole instructions
    patch, replace, data        -> "bytes"
    patch, from_symbol, data    -> "ptr"
    patch, from_symbol, code    -> "keep2" when the instruction is an opcode word and
                                   that address (jsr.l, lea.l, move.l #imm); otherwise
                                   "bytes" kind code over the whole instruction, with
                                   an abs32 reloc to the symbol
  Code or data is decided by address (below TEXT_END is .text) and checked by
  disassembling the stock image: a site in .text must start and end on
  instruction boundaries, found the same from every starting point tried.

Only addresses, stock instruction bytes at the sites and the mod's own source
are written - no other firmware bytes.
"""
import collections
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

BASE = 0x40000400
TEXT_END = 0x401bea90          # end of .text in OS 1.73's main image: re/symbols.toml's first rodata object


def gated_out(gate, params, owner):
    if gate is None:
        return False
    if "&" in gate:
        return any(gated_out(g.strip(), params, owner) for g in gate.split("&"))
    if "==" in gate:
        name, _, want = gate.partition("==")
        name = name.strip()
        if name not in params:
            sys.exit("%s: gate names unknown param %r" % (owner, name))
        return int(params[name]) != int(want, 0)
    neg = gate.startswith("!")
    name = gate.lstrip("!").strip()
    if name not in params:
        sys.exit("%s: gate names unknown param %r" % (owner, name))
    on = bool(int(params[name]))
    return on if neg else not on


class Disasm:
    def __init__(self, img_path):
        self.path = img_path

    def _insns(self, start, stop):
        out = subprocess.run(
            ["m68k-linux-gnu-objdump", "-D", "-b", "binary", "-m", "m68k:cfv4e",
             "--adjust-vma=0x%x" % BASE, "--start-address=0x%x" % start,
             "--stop-address=0x%x" % stop, self.path],
            capture_output=True, text=True, check=True).stdout
        res = []
        for line in out.splitlines():
            m = re.match(r"\s*([0-9a-f]+):\s+((?:[0-9a-f]{4} )+)\s*(.*)", line)
            if m:
                res.append((int(m.group(1), 16), len(m.group(2).split()) * 2, m.group(3)))
        return res

    def bounds(self, addr, length):
        """The instructions covering [addr, addr+length): (start, end, texts), agreed on
        by every starting point from 32 to 126 bytes before."""
        seen = collections.Counter()
        for back in range(0x20, 0x80, 2):
            ins = [i for i in self._insns(addr - back, addr + length + 16)
                   if i[0] + i[1] > addr and i[0] < addr + length]
            if ins:
                seen[tuple(ins)] += 1
        (ins, n), = seen.most_common(1)
        if n != sum(seen.values()):
            sys.exit("0x%08x: instruction boundaries disagree between starting points" % addr)
        if any(t.startswith(".short") for _, _, t in ins):
            sys.exit("0x%08x: not instructions: %s" % (addr, ins))
        return ins[0][0], ins[-1][0] + ins[-1][1], [t for _, _, t in ins]


def main(src, mdir, new_id, stock_syx):
    src = Path(src)
    here = Path(__file__).resolve().parent.parent
    from elekloader import formats
    st, dev, _ = formats.load(stock_syx)
    img = formats.main_image(st, dev)
    tmp = here / "out"
    tmp.mkdir(exist_ok=True)
    img_path = tmp / "stock-main.bin"          # scratch, under .gitignore'd out/
    img_path.write_bytes(img)
    dis = Disasm(str(img_path))

    def stock(addr, n):
        return img[addr - BASE:addr - BASE + n]

    mod = tomllib.loads((src / "mods" / mdir / "mod.toml").read_text())
    owner = mod["mod"]["id"]
    params = dict(mod.get("params", {}))
    needs_shared = bool(mod.get("requires", {}).get("shared"))
    reg = tomllib.loads((src / "registry" / "allocations.toml").read_text())
    dets = [d for d in reg.get("detour", []) if d["owner"] == owner
            and not gated_out(d.get("gate"), params, owner)]
    pats = [p for p in reg.get("patch", []) if p["owner"] == owner
            and not gated_out(p.get("gate"), params, owner)]
    prefix = new_id.replace("-", "_") + "_"

    names = [d["entry"] for d in dets] + [p["from_symbol"] for p in pats if "from_symbol" in p]
    rename = {}
    for n in names:
        rename[n] = n if n.startswith(prefix) else prefix + n

    text = (src / "mods" / mdir / mod["sources"]["stub"]).read_text()
    out_dir = here / new_id
    out_dir.mkdir(exist_ok=True)

    # includes
    text = text.replace('.include "symbols.inc"', '.include "../include/ar2-1.73.inc"')
    if needs_shared:
        text = re.sub(r'^\s*\.include\s+"shared\.inc"\s*\n', "", text, flags=re.M)
    for m in re.finditer(r'\.include\s+"mods/%s/([^"]+)"' % re.escape(mdir), text):
        shutil.copy(src / "mods" / mdir / m.group(1), out_dir / m.group(1))
    text = re.sub(r'\.include\s+"mods/%s/([^"]+)"' % re.escape(mdir), r'.include "\1"', text)
    if re.search(r'\.include\s+"(?!\.\./include/|[\w.-]+\.inc")', text):
        sys.exit("an include this tool does not know how to map")
    # sections
    def sect(m):
        d = ".pushsection .text" if m.group(2) == "pushsection" else ".text"
        return '%s%s%s| elemod: was .%s %s,"%s"' % (
            m.group(1), d, " " * max(1, 34 - len(m.group(1)) - len(d)), m.group(2), m.group(3), m.group(4))
    text = re.sub(r'^(\s*)\.(section|pushsection)\s+(\.\w+)\s*,\s*"(\w+)"(.*)$', sect, text, flags=re.M)
    if re.search(r"^\s*\.(section|pushsection)\b(?!\s+\.text)", text, re.M):
        sys.exit("a section directive this tool does not map")
    # globals: a global alias, prefixed with the mod id, on the line before each
    # label a site names. The stub's own references keep using the original local
    # label, so the assembler encodes them exactly as rytm-mods' build did (a
    # reference to a global symbol is never relaxed to PC-relative).
    macro_done = set()
    for old, new in sorted(rename.items()):
        pat = re.compile(r"^(%s:)" % re.escape(old), re.M)
        n = len(pat.findall(text))
        if n == 1:
            if new == old:
                text = pat.sub("        .globl  %s\n\\1" % new, text)
            else:
                text = pat.sub("        .globl  %s\n%s:\n\\1" % (new, new), text)
            continue
        # a label a macro makes, `base\arg:` - the alias goes in the macro, so every
        # use of the macro gets one
        mac = [m for m in re.finditer(r"^(\w+)\\(\w+):", text, re.M) if old.startswith(m.group(1))]
        mac = [m for m in mac if len(m.group(1)) == max(len(x.group(1)) for x in mac)]
        if n or len(mac) != 1:
            sys.exit("label %s: defined %d times, %d macro patterns" % (old, n, len(mac)))
        m = mac[0]
        if m.group(0) not in macro_done:
            macro_done.add(m.group(0))
            alias = prefix + m.group(1) + "\\" + m.group(2)
            text = text.replace(m.group(0), "        .globl  %s\n%s:\n%s" % (alias, alias, m.group(0)), 1)

    # params and header
    lines = text.splitlines(keepends=True)
    first_inc = next(i for i, l in enumerate(lines) if re.match(r"\s*\.include", l))
    eqs = ""
    if params:
        eqs = ("\n        | elemod: rytm-mods' default build params, as its build passed them\n" +
               "".join("        .equ    P_%s, %d\n" % (k.upper(), int(v)) for k, v in sorted(params.items())) +
               "\n")
    head = ("        | SPDX-License-Identifier: GPL-2.0-only\n"
            "        | %s - elemod port of rytm-mods-src %s (MrScruff). Code unchanged but for\n"
            "        | the lines marked elemod and the global labels the sites name, each an alias\n"
            "        | carrying the mod id beside the original label.\n        |\n" % (new_id, mdir))
    text = head + "".join(lines[:first_inc + 1]) + eqs + "".join(lines[first_inc + 1:])
    if needs_shared:
        text = text.rstrip("\n") + ("\n\n        | elemod: 0000-shared's runtime, a private copy in this unit\n"
                                    "        .text\n        .include \"../shared/shared.s\"\n")
    (out_dir / (new_id + ".s")).write_text(text, newline="\n")

    # sites
    sites = []
    for d in sorted(dets, key=lambda d: d["addr"]):
        want = bytes.fromhex(d["expect"])
        if stock(d["addr"], len(want)) != want:
            sys.exit("detour 0x%08x: stock differs" % d["addr"])
        s, e, t = dis.bounds(d["addr"], len(want))
        if s != d["addr"]:
            sys.exit("detour 0x%08x: starts inside an instruction %s" % (d["addr"], t))
        if e != d["addr"] + len(want):
            # the jmp lands across an instruction the stub re-emits: the site takes
            # it whole, which is safe only if the stub rejoins at or past its end
            rj = d.get("rejoin")
            if not (rj == "none" or (isinstance(rj, int) and rj >= e)):
                sys.exit("detour 0x%08x: %s does not cover whole instructions %s, rejoin %r"
                         % (d["addr"], d["expect"], t, rj))
            print("  detour 0x%08x: stock widened from %d to %d bytes (whole %s; rejoin %s)"
                  % (d["addr"], len(want), e - s, " / ".join(t), rj if rj == "none" else "0x%08x" % rj))
        sites.append({"addr": "0x%08x" % d["addr"], "stock": stock(s, e - s).hex(), "op": "jmp",
                      "target": rename[d["entry"]]})
    for p in sorted(pats, key=lambda p: p["addr"]):
        a, want = p["addr"], bytes.fromhex(p["expect"])
        if stock(a, len(want)) != want:
            sys.exit("patch 0x%08x: stock differs" % a)
        code = a < TEXT_END
        if code:
            s, e, t = dis.bounds(a, len(want))
        else:
            s, e = a, a + len(want)
        old = stock(s, e - s)
        if "from_symbol" in p:
            if not code:
                if len(want) != 4:
                    sys.exit("pointer patch 0x%08x is not 4 bytes" % a)
                sites.append({"addr": "0x%08x" % a, "stock": p["expect"], "op": "ptr",
                              "target": rename[p["from_symbol"]]})
            elif a - s == 2 and e - s == 6:
                # an opcode word and its 32-bit address (jsr.l, lea.l, move.l #imm):
                # elemod's keep2 keeps the opcode and writes the symbol's address
                sites.append({"addr": "0x%08x" % s, "stock": old.hex(), "op": "keep2",
                              "target": rename[p["from_symbol"]]})
            else:
                new = old[:a - s] + bytes(4) + old[a - s + 4:]
                sites.append({"addr": "0x%08x" % s, "stock": old.hex(), "op": "bytes",
                              "new": new.hex(), "kind": "code",
                              "relocs": [[a - s, "abs32", "sym:" + rename[p["from_symbol"]], 0]]})
        else:
            rep = bytes.fromhex(p["replace"])
            new = old[:a - s] + rep + old[a - s + len(rep):]
            site = {"addr": "0x%08x" % s, "stock": old.hex(), "op": "bytes", "new": new.hex()}
            if code:
                site["kind"] = "code"
            sites.append(site)

    summary = " ".join(mod["mod"].get("summary", "").split())
    manifest = {
        "id": new_id, "version": "1.0", "title": mod["mod"]["title"], "category": "",
        "author": "MrScruff (rytm-mods); elemod port: Iced-Cream", "license": "GPL-2.0-only",
        "description": summary + " Port of rytm-mods %s." % mdir,
        "device": "analog-rytm-mk2", "os": "1.73",
        "sources": [new_id + ".s"], "sites": sites, "requires": ["core"],
    }
    mpath = out_dir / "mod.json"
    if mpath.exists():                  # keep hand-edited fields
        old = json.loads(mpath.read_text())
        for k in ("title", "category", "description", "requires"):
            if k in old:
                manifest[k] = old[k]
    mpath.write_text(json.dumps(manifest, indent=1) + "\n", newline="\n")
    print("%s: %d sites (%d detours, %d patches), %d globals, params %s, shared %s"
          % (new_id, len(sites), len(dets), len(pats), len(set(rename.values())), params or "-", needs_shared))


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    main(*sys.argv[1:])
