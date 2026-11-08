import random, struct, subprocess, sys
def syms(binp):
    out = subprocess.check_output(["m68k-linux-gnu-nm", binp]).decode().split("\n")
    return {l.split()[2]: int(l.split()[0], 16) for l in out if len(l.split()) == 3}
S = syms("h/old"); S2 = syms("h/new")
base = S["m_rx"]; inlen = S["m_in_end"] - base; outlen = S["m_out_end"] - base
assert inlen == S2["m_in_end"] - S2["m_rx"] and outlen == S2["m_out_end"] - S2["m_rx"]
off = {k: v - base for k, v in S.items() if base <= v <= S["m_out_end"]}
EXT = [0, 1, -1, 0x7fffffff, -0x80000000, 0x40000000, -0x40000000, 0x7fff7fff, 0x7fffbfff]
def w32(r, ext=0.15):
    if r.random() < ext: return r.choice(EXT) & 0xffffffff
    if r.random() < 0.3: return r.randrange(-1 << 26, 1 << 26) & 0xffffffff   # audio-sized
    return r.getrandbits(32)
def case(seed, nblk):
    r = random.Random(seed)
    slot = list(range(8)); r.shuffle(slot) if r.random() < 0.5 else None
    owner = [r.randrange(12) for _ in range(8)]
    vca = [r.randrange(65536) for _ in range(16)]
    pol = [r.getrandbits(32) for _ in range(12)]
    d6 = r.getrandbits(12)
    blob = b""
    for b in range(nblk):
        m = bytearray(inlen)
        def put(name, data, o=0): m[off[name] + o: off[name] + o + len(data)] = data
        put("m_rx", b"".join(struct.pack(">I", w32(r)) for _ in range((32 * 48 + 64) // 4)))
        put("m_out", b"".join(struct.pack(">I", w32(r)) for _ in range((2048 + 64) // 4)))
        put("m_slot", struct.pack(">8I", *slot))
        for i in range(16):
            if r.random() < 0.3: vca[i] = r.choice([0, 0, 65535, r.randrange(65536)])
        if r.random() < 0.2: owner[r.randrange(8)] = r.randrange(12)
        for i in range(12):
            if r.random() < 0.15: pol[i] ^= 0x100
        if r.random() < 0.2: d6 ^= 1 << r.randrange(12)
        if r.random() < 0.25: vca = [0] * 16
        if r.random() < 0.1: d6 = 0xfff
        put("m_vca", struct.pack(">16H", *vca))
        put("m_owner", bytes(owner))
        put("hpf_mod", b"".join(struct.pack(">I", r.getrandbits(32)) for _ in range(12)))
        put("shp_mod", struct.pack(">12I", *pol))
        put("mod_frac", bytes(r.getrandbits(8) for _ in range(12)))
        fc = []
        for p in range(4):
            if r.random() < 0.3:
                fc += [0x7fffbfff, (-0x7fffbfff) & 0xffffffff, 0x7fff7fff] * 2
            else:
                for q in range(2):
                    if r.random() < 0.3: fc += [0x7fffbfff, (-0x7fffbfff) & 0xffffffff, 0x7fff7fff]
                    else: fc += [w32(r), w32(r), w32(r, 0.05) if r.random() < 0.3 else r.randrange(0x60000000, 0x7fffffff)]
        put("flt_coef", struct.pack(">24I", *fc))
        put("bq_on", bytes(r.choice([0, 1]) for _ in range(8)))
        put("bq_coefs", b"".join(struct.pack(">I", w32(r)) for _ in range(40)))
        put("m_d6", struct.pack(">I", d6))
        blob += bytes(m)
    return blob
import cfsim
def run(binp, blob):
    return cfsim.run(binp, blob)[0]
n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
nblk = 12; bad = 0; total = 0
for seed in range(n):
    blob = case(seed, nblk)
    a, b = run("h/old", blob), run("h/new", blob)
    assert len(a) == len(b) == outlen * nblk, (len(a), len(b))
    total += len(a)
    if a != b:
        bad += 1
        for k in range(nblk):
            x, y = a[k*outlen:(k+1)*outlen], b[k*outlen:(k+1)*outlen]
            if x != y:
                d = [i for i in range(outlen) if x[i] != y[i]]
                names = sorted(off.items(), key=lambda t: t[1])
                where = max((nm for nm in names if nm[1] <= d[0]), key=lambda t: t[1])
                print(f"seed {seed} blk {k}: {len(d)} bytes differ, first at +{d[0]} ({where[0]}+{d[0]-where[1]})"); break
        if bad > 5: break
print(f"{n} cases x {nblk} blocks, {total} output bytes each side, {bad} cases differ")
