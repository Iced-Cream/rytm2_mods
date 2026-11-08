import struct, random, cfsim, subprocess
M32=0xffffffff
exec(open('drive.py').read().split('def case')[0])
def blk(r, pairs_on, bq, vz=False):
    m = bytearray(inlen)
    def put(name, data): m[off[name]:off[name]+len(data)] = data
    put("m_rx", b"".join(struct.pack(">i", r.randrange(-1<<26,1<<26)) for _ in range((32*48+64)//4)))
    put("m_out", b"".join(struct.pack(">i", r.randrange(-1<<20,1<<20)) for _ in range((2048+64)//4)))
    put("m_slot", struct.pack(">8I", *range(8)))
    put("m_vca", struct.pack(">16H", *([0]*16 if vz else [20000]*8 + [30000]*8)))
    put("m_owner", bytes(range(8)))
    fc=[]
    for p in range(4):
        for q in range(2):
            fc += [0x60000000, (-0x5f000000)&M32, 0x70000000] if pairs_on[p] else [0x7fffbfff, (-0x7fffbfff)&M32, 0x7fff7fff]
    put("flt_coef", struct.pack(">24I", *fc))
    put("bq_on", bytes(bq))
    put("bq_coefs", struct.pack(">40i", *([0x10000000, 0x20000000, 0x10000000, 0x60000000, -0x30000000]*8)))
    return bytes(m)
S = {"DAC SUM, no filter": ([0]*4, [0]*8), "one LP2": ([0]*4, [1]+[0]*7),
     "DAC SUM, voices silent": ([0]*4, [0]*8, True), "every slot LP1": ([1]*4, [0]*8), "every slot LP2": ([0]*4, [1]*8)}
for name, t in S.items():
    p, b = t[0], t[1]; vz = len(t) > 2
    res = []
    for v in ("old", "new"):
        r = random.Random(1)
        one = cfsim.run(f"h/{v}", blk(r, p, b, vz))[1]
        r = random.Random(1)
        two = cfsim.run(f"h/{v}", blk(r, p, b, vz) + blk(r, p, b, vz))[1]
        res.append(two - one)   # one steady block (second), harness I/O included
    print(f"{name:22s} old {res[0]:5d}  new {res[1]:5d}  ({100*(res[0]-res[1])/res[0]:.0f}% fewer)")
