"""A small ColdFire V4e interpreter for the harness: the instructions the
voice-dac segments use, from objdump's disassembly, EMAC by the PRM's model
(fractional, saturating, truncating: MACSR 0xa0)."""
import re, subprocess, struct
import os
SAT32 = os.environ.get("SAT32") == "1"
M32 = 0xffffffff
def s32(v): v &= M32; return v - (1 << 32) if v & 0x80000000 else v
class Sim:
    def __init__(self, elf):
        self.prog = {}
        dis = subprocess.check_output(["m68k-linux-gnu-objdump", "-d", "--no-show-raw-insn", elf]).decode()
        for l in dis.split("\n"):
            m = re.match(r"^([0-9a-f]+):\t(\S+)\s*(.*)$", l)
            if m: self.prog[int(m.group(1), 16)] = (m.group(2), m.group(3).strip())
        self.addrs = sorted(self.prog)
        self.nxt = {a: b for a, b in zip(self.addrs, self.addrs[1:] + [None])}
        hdr = subprocess.check_output(["m68k-linux-gnu-objdump", "-h", elf]).decode()
        self.mem = bytearray(0x10000)
        self.base = 0x80000000
        for l in hdr.split("\n"):
            p = l.split()
            if len(p) >= 6 and p[1] in (".text", ".data"):
                size, vma = int(p[2], 16), int(p[3], 16)
                data = subprocess.check_output(["m68k-linux-gnu-objcopy", "-O", "binary", "-j", p[1], elf, "/dev/stdout"])
                self.mem[vma - self.base: vma - self.base + size] = data[:size]
        self.d = [0] * 8; self.a = [0] * 8
        self.a[7] = self.base + 0xff00
        self.acc = [0] * 4; self.pav = [0] * 4
        self.macsr = 0; self.x = self.n = self.z = self.v = self.c = 0
        self.stdin = b""; self.stdout = bytearray(); self.done = False; self.steps = 0
    # memory
    def chk(self, a, n):
        o = (a & M32) - self.base
        if o < 0 or o + n > len(self.mem): raise Exception(f"bad address {a:#x}")
        return o
    def rd(self, a, n):
        o = self.chk(a, n); return int.from_bytes(self.mem[o:o + n], "big")
    def wr(self, a, n, v):
        o = self.chk(a, n); self.mem[o:o + n] = (v & ((1 << 8 * n) - 1)).to_bytes(n, "big")
    # registers
    def reg(self, r):
        if r == "%fp": r = "%a6"
        if r == "%sp": r = "%a7"
        return r[1], int(r[2])
    def getr(self, r):
        k, i = self.reg(r); return (self.d if k == "d" else self.a)[i]
    def setr(self, r, v):
        k, i = self.reg(r); (self.d if k == "d" else self.a)[i] = v & M32
    # operands
    def ea(self, op, size, pc):
        """-> ('reg', name) | ('imm', v) | ('mem', addr)"""
        op = op.strip()
        m = re.match(r"^#(-?(0x)?[0-9a-f]+)$", op)
        if m: return ("imm", int(m.group(1), 0) & M32)
        if re.match(r"^%(d[0-7]|a[0-7]|fp|sp)$", op): return ("reg", op)
        m = re.match(r"^%(\w+)@$", op)
        if m: return ("mem", self.getr("%" + m.group(1)))
        m = re.match(r"^%(\w+)@\+$", op)
        if m:
            r = "%" + m.group(1); a = self.getr(r); self.setr(r, a + size); return ("mem", a)
        m = re.match(r"^%(\w+)@-$", op)
        if m:
            r = "%" + m.group(1); a = (self.getr(r) - size) & M32; self.setr(r, a); return ("mem", a)
        m = re.match(r"^%(\w+)@\((-?\d+)\)$", op)
        if m: return ("mem", (self.getr("%" + m.group(1)) + int(m.group(2))) & M32)
        m = re.match(r"^%(\w+)@\((-?[0-9a-f]+),%(\w+):l(?::(\d))?\)$", op)
        if m:
            base = "%" + m.group(1); disp = int(m.group(2), 16)
            if disp & 0x80: disp -= 0x100 if disp < 0x100 else 0
            sc = int(m.group(4) or 1)
            return ("mem", (self.getr(base) + disp + self.getr("%" + m.group(3)) * sc) & M32)
        m = re.match(r"^%pc@\(([0-9a-f]+) <.*>\)$", op)
        if m: return ("mem", int(m.group(1), 16))
        m = re.match(r"^([0-9a-f]+) <.*>$", op)
        if m: return ("mem", int(m.group(1), 16))
        raise Exception("operand " + op)
    def get(self, e, size):
        k, v = e
        if k == "imm": return v & ((1 << 8 * size) - 1)
        if k == "reg": return self.getr(v) & ((1 << 8 * size) - 1)
        return self.rd(v, size)
    def put(self, e, size, val):
        k, v = e
        if k == "reg":
            if size == 4 or v.startswith("%a"): self.setr(v, val)
            else:
                old = self.getr(v); mask = (1 << 8 * size) - 1
                self.setr(v, (old & ~mask) | (val & mask))
        elif k == "mem": self.wr(v, size, val)
        else: raise Exception("put imm")
    def flags_logic(self, r):
        r &= M32; self.n = r >> 31; self.z = int(r == 0); self.v = 0; self.c = 0
    def flags_add(self, a, b, r, sub=False):
        a &= M32; b &= M32; rr = r & M32
        self.n = rr >> 31; self.z = int(rr == 0)
        if sub:
            self.c = int(b > a)
            self.v = int(((a ^ b) & (a ^ rr)) >> 31 & 1)
        else:
            self.c = int(a + b > M32)
            self.v = int((~(a ^ b) & (a ^ rr)) >> 31 & 1)
    def cond(self, cc):
        n, z, v, c = self.n, self.z, self.v, self.c
        return {"ra": True, "eq": z, "ne": not z, "pl": not n, "mi": n, "lt": n != v, "ge": n == v,
                "le": z or n != v, "gt": not z and n == v, "cs": c, "cc": not c, "hi": not c and not z,
                "ls": c or z}[cc]
    # EMAC, fractional: the accumulator kept as a Q39 integer, 48 bits
    def sat48(self, i, v):
        lim = (1 << 39) if SAT32 else (1 << 47)
        if v >= lim or v < -lim:
            self.pav[i] = 1
            v = lim - 1 if v > 0 else -lim
        return v
    def emac(self, sub, ry, rx, i):
        p = s32(ry) * s32(rx)               # Q62
        t = (p << 1) >> 24                  # Q63 -> Q39, truncated
        self.acc[i] = self.sat48(i, self.acc[i] - t if sub else self.acc[i] + t)
    def acc_out(self, i):
        v = self.acc[i] >> 8                # Q31, truncated
        if v > 0x7fffffff: v = 0x7fffffff
        if v < -0x80000000: v = -0x80000000
        return v & M32
    def run(self, pc, maxsteps=10**8):
        while not self.done:
            self.steps += 1
            if self.steps > maxsteps: raise Exception("runaway")
            mn, ops = self.prog[pc]
            npc = self.nxt[pc]
            pc = self.step(pc, npc, mn, ops)
        return
    def split(self, ops):
        out, depth, cur = [], 0, ""
        for ch in ops:
            if ch == "(": depth += 1
            if ch == ")": depth -= 1
            if ch == "," and depth == 0: out.append(cur); cur = ""
            else: cur += ch
        if cur: out.append(cur)
        return out
    def step(self, pc, npc, mn, ops):
        o = self.split(ops)
        sz = {"l": 4, "w": 2, "b": 1}
        m = re.match(r"^(mac|msac)l$", mn)
        if m:
            sub = m.group(1) == "msac"
            ry, rx = self.getr(o[0]), self.getr(o[1])
            if len(o) == 3:
                acc = int(o[2][-1])
            else:
                acc = int(o[4][-1])
                e = self.ea(o[2], 4, pc); val = self.get(e, 4)
            self.emac(sub, ry, rx, acc)
            if len(o) == 5: self.setr(o[3], val)
            return npc
        if mn == "movclrl":
            i = int(o[0][-1]); self.setr(o[1], self.acc_out(i)); self.acc[i] = 0; self.pav[i] = 0; return npc
        if mn == "movel" and o[1].startswith("%acc"):
            i = int(o[1][-1]); self.acc[i] = s32(self.get(self.ea(o[0], 4, pc), 4)) << 8; self.pav[i] = 0; return npc
        if mn == "movel" and o[1] == "%macsr":
            self.macsr = self.get(self.ea(o[0], 4, pc), 4); assert self.macsr == 0xa0; return npc
        if mn == "movel" and o[0] == "%macsr":
            self.setr(o[1], self.macsr); return npc
        if mn == "satsl":
            if self.v:
                r = self.getr(o[0]); self.setr(o[0], 0x7fffffff if r >> 31 else 0x80000000)
            self.flags_logic(self.getr(o[0])); return npc
        m = re.match(r"^b(ra|eq|ne|pl|mi|lt|ge|le|gt|cs|cc|hi|ls)[sw]$", mn)
        if m:
            t = int(ops.split()[0], 16)
            return t if self.cond(m.group(1)) else npc
        if mn == "jsr":
            t = self.ea(o[0], 4, pc)[1]; self.a[7] = (self.a[7] - 4) & M32; self.wr(self.a[7], 4, npc); return t
        if mn == "rts":
            t = self.rd(self.a[7], 4); self.a[7] = (self.a[7] + 4) & M32; return t
        if mn == "trap":
            self.syscall(); return npc
        if mn == "lea":
            self.setr(o[1], self.ea(o[0], 4, pc)[1]); return npc
        if mn == "moveq":
            v = int(o[0][1:], 0); self.setr(o[1], v); self.flags_logic(v); return npc
        m = re.match(r"^move([lwb])$", mn)
        if m:
            s = sz[m.group(1)]; v = self.get(self.ea(o[0], s, pc), s)
            self.put(self.ea(o[1], s, pc), s, v)
            self.flags_logic(v << (32 - 8 * s)); return npc
        if mn == "moveal":
            v = self.get(self.ea(o[0], 4, pc), 4); self.setr(o[1], v); return npc
        m = re.match(r"^mvz([wb])$", mn)
        if m:
            s = sz[m.group(1)]; v = self.get(self.ea(o[0], s, pc), s); self.setr(o[1], v); self.flags_logic(v); return npc
        if mn == "moveml":
            regs = None
            if o[0].startswith("%sp@") or o[0].startswith("%a7@"):
                base = self.a[7] if o[0] in ("%sp@", "%a7@") else None; regs = o[1]; load = True
            else:
                base = self.a[7]; regs = o[0]; load = False
                assert o[1] == "%sp@"
            names = []
            for part in regs.split("/"):
                if "-" in part:
                    x, y = part.split("-"); k = x[1]
                    names += ["%" + k + str(j) for j in range(int(x[2]), int(y[2]) + 1)]
                else: names.append(part)
            for j, r in enumerate(names):
                if load: self.setr(r, self.rd(base + 4 * j, 4))
                else: self.wr(base + 4 * j, 4, self.getr(r))
            return npc
        m = re.match(r"^(add|sub|cmp)(a?)(i?|q?)l$", mn)
        if m:
            op = m.group(1); isa = m.group(2) == "a" or o[1].startswith("%a") or o[1] in ("%fp", "%sp")
            src = self.get(self.ea(o[0], 4, pc), 4)
            de = self.ea(o[1], 4, pc); dst = self.get(de, 4)
            if op == "add": r = dst + src
            else: r = dst - src
            if not isa or op == "cmp": self.flags_add(dst, src, r, sub=op != "add")
            if op != "cmp": self.put(de, 4, r)
            return npc
        m = re.match(r"^(and|or|eor)(i?)l$", mn)
        if m:
            src = self.get(self.ea(o[0], 4, pc), 4); de = self.ea(o[1], 4, pc); dst = self.get(de, 4)
            r = {"and": dst & src, "or": dst | src, "eor": dst ^ src}[m.group(1)]
            self.put(de, 4, r); self.flags_logic(r); return npc
        if mn == "negl":
            v = self.getr(o[0]); r = (-v) & M32; self.flags_add(0, v, r, sub=True); self.setr(o[0], r); return npc
        if mn == "swap":
            v = self.getr(o[0]); r = ((v << 16) | (v >> 16)) & M32; self.setr(o[0], r); self.flags_logic(r); return npc
        if mn == "clrw":
            v = self.getr(o[0]); self.setr(o[0], v & 0xffff0000); self.flags_logic(0); return npc
        if mn == "clrl":
            self.put(self.ea(o[0], 4, pc), 4, 0); self.flags_logic(0); return npc
        m = re.match(r"^(lsl|lsr|asr)l$", mn)
        if m:
            cnt = self.get(self.ea(o[0], 4, pc), 4) & 63; v = self.getr(o[1])
            if m.group(1) == "lsl": r = (v << cnt) & M32; c = (v >> (32 - cnt)) & 1 if cnt else 0
            elif m.group(1) == "lsr": r = v >> cnt if cnt < 32 else 0; c = (v >> (cnt - 1)) & 1 if cnt else 0
            else: r = (s32(v) >> min(cnt, 31)) & M32; c = (s32(v) >> (cnt - 1)) & 1 if cnt else 0
            self.setr(o[1], r); self.flags_logic(r); self.c = c; return npc
        if mn == "btst":
            b = self.get(self.ea(o[0], 4, pc), 4); e = self.ea(o[1], 1 if not o[1].startswith("%d") else 4, pc)
            if e[0] == "reg": self.z = int(not (self.getr(e[1]) >> (b & 31)) & 1)
            else: self.z = int(not (self.rd(e[1], 1) >> (b & 7)) & 1)
            return npc
        m = re.match(r"^tst([lwb])$", mn)
        if m:
            s = sz[m.group(1)]; v = self.get(self.ea(o[0], s, pc), s); self.flags_logic(v << (32 - 8 * s)); return npc
        if mn == "mulul":
            r = (self.getr(o[0]) * self.getr(o[1])) & M32; self.setr(o[1], r); self.flags_logic(r); return npc
        if mn == "remul":      # remul %dy,%dr,%dq with r == q: divu.l
            dv = self.getr(o[0]); nm = self.getr(o[2]); assert o[1] == o[2] and dv
            self.setr(o[2], nm // dv); self.flags_logic(nm // dv); return npc
        raise Exception(f"{pc:#x}: {mn} {ops}")
    def syscall(self):
        n = self.d[0]
        if n == 1: self.done = True
        elif n == 3:
            k = min(self.d[3], len(self.stdin)); buf = self.stdin[:k]; self.stdin = self.stdin[k:]
            o = self.chk(self.d[2], k); self.mem[o:o + k] = buf; self.d[0] = k
        elif n == 4:
            o = self.chk(self.d[2], self.d[3]); self.stdout += self.mem[o:o + self.d[3]]; self.d[0] = self.d[3]
        else: raise Exception(f"syscall {n}")
def run(elf, blob):
    s = Sim(elf); s.stdin = blob
    start = int([l for l in subprocess.check_output(["m68k-linux-gnu-nm", elf]).decode().split("\n") if l.endswith(" _start")][0].split()[0], 16)
    s.run(start); return bytes(s.stdout), s.steps
