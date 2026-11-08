"""mk_selfcheck.py OLD.s NEW.s OUT.s: voice-dac's 1.74 source with a
self-check, for the emulator only (never a release build). In every block
with DAC SUM on, vs_body runs OLD's pan pass .. sum on the block's inputs,
keeps what it wrote, puts the inputs back, runs NEW's on the same inputs and
compares every byte either wrote. Counters (globals, in the map):
  voice_dac_sc_n     blocks checked
  voice_dac_sc_bad   blocks where OLD and NEW wrote anything different
  voice_dac_sc_where first mismatch: area index << 16 | byte offset
  voice_dac_sc_blk   sc_n at the first mismatch
The areas: 0 RXBUF, 1 the PRE slot, 2 flt_coef, 3 flt_key, 4 frq_frac,
5 flt_kfrac, 6 hpf_state, 7 bq_coefs, 8 bq_state, 9 bq_on, 10 shp_state,
11 the stack's (cL, cR) and entry tables."""
import sys
old, new, out = (open(sys.argv[1]).read(), open(sys.argv[2]).read(), sys.argv[3])
START = "        lea     COEF(%sp),%a4                     | above the saved MACSR\n"
def region(s):
    a = s.index(START); b = s.index("10:\n", a) + len("10:\n"); return a, b
oa, ob = region(old)
old_r = old[oa:ob].replace("jsr     bq_run ", "jsr     bq_run_old ")
assert "bq_run_old" in old_r
bq_a = old.index("bq_run:\n"); bq_b = old.index("        rts\n", bq_a) + len("        rts\n")
old_bq = old[bq_a:bq_b].replace("bq_run:\n", "bq_run_old:\n", 1)
na, nb = region(new)
pre = """        .if     1                                 | selfcheck: 1.6's pass first
        move.l  %d6,sc_d6
        lea     COEF(%sp),%a0
        move.l  %a0,sc_tab+11*8
        bsr.w   sc_setup
        lea     sc_in,%a1
        bsr.w   sc_copy_out                       | the inputs, kept
""" + old_r + """        lea     sc_old,%a1
        bsr.w   sc_copy_out                       | what 1.6 wrote
        lea     sc_in,%a1
        bsr.w   sc_copy_in                        | the inputs back
        move.l  sc_d6,%d6
        .endif
"""
post = """        bsr.w   sc_compare                        | selfcheck: 1.7 against 1.6
"""
s = new[:na] + pre + new[na:nb] + post + new[nb:]
s = s.replace("        .align  2\nbq_run:\n", "        .align  2\n" + old_bq + "\n        .align  2\nbq_run:\n", 1)
areas = [  # sizes in bytes, multiples of 4
         ("RXBUF", 32 * 48 + 8), ("0", 32 * 64), ("flt_coef", 96), ("flt_key", 32), ("frq_frac", 8),
         ("flt_kfrac", 8), ("hpf_state", 64), ("bq_coefs", 160), ("bq_state", 128), ("bq_on", 8),
         ("shp_state", 192), ("0", 100)]
tot = sum(n for _, n in areas)
tab = "\n".join(f"        .long   {a}, {n}" for a, n in areas)
s += f"""
        | ---- selfcheck (emulator only) ----
        .text
        .align  2
sc_setup:                                         | the PRE slot's address
        move.l  OUT_IDX,%d0
        moveq   #11,%d1
        lsl.l   %d1,%d0
        add.l   #OUT_RING,%d0
        move.l  %d0,sc_tab+8
        rts
sc_copy_out:                                      | areas -> (a1)
        lea     sc_tab,%a2
        moveq   #12-1,%d2
1:      move.l  (%a2)+,%a0
        move.l  (%a2)+,%d1
2:      move.l  (%a0)+,(%a1)+
        subq.l  #4,%d1
        bne.s   2b
        subq.l  #1,%d2
        bpl.s   1b
        rts
sc_copy_in:                                       | (a1) -> areas
        lea     sc_tab,%a2
        moveq   #12-1,%d2
1:      move.l  (%a2)+,%a0
        move.l  (%a2)+,%d1
2:      move.l  (%a1)+,(%a0)+
        subq.l  #4,%d1
        bne.s   2b
        subq.l  #1,%d2
        bpl.s   1b
        rts
sc_compare:
        lea     -24(%sp),%sp
        movem.l %d0-%d3/%a0-%a1,(%sp)
        addq.l  #1,voice_dac_sc_n
        lea     sc_tab,%a2
        lea     sc_old,%a1
        moveq   #0,%d2                            | the area
1:      move.l  (%a2)+,%a0
        move.l  (%a2)+,%d1
        moveq   #0,%d3                            | the offset
2:      move.l  (%a0)+,%d0
        cmp.l   (%a1)+,%d0
        bne.s   8f
        addq.l  #4,%d3
        cmp.l   %d1,%d3
        blt.s   2b
        addq.l  #1,%d2
        moveq   #12,%d0
        cmp.l   %d0,%d2
        blt.s   1b
        bra.s   9f
8:      addq.l  #1,voice_dac_sc_bad
        tst.l   voice_dac_sc_blk
        bne.s   9f
        swap    %d2
        clr.w   %d2
        or.l    %d3,%d2
        move.l  %d2,voice_dac_sc_where
        move.l  voice_dac_sc_n,%d0
        move.l  %d0,voice_dac_sc_blk
9:      movem.l (%sp),%d0-%d3/%a0-%a1
        lea     24(%sp),%sp
        rts
        .align  2
sc_tab:
{tab}
sc_d6:  .long   0
        .globl  voice_dac_sc_n, voice_dac_sc_bad, voice_dac_sc_where, voice_dac_sc_blk
voice_dac_sc_n:     .long 0
voice_dac_sc_bad:   .long 0
voice_dac_sc_where: .long 0
voice_dac_sc_blk:   .long 0
sc_in:  .space  {tot}
sc_old: .space  {tot}
        .align  2
"""
open(out, "w").write(s)
