import sys, re
def seg(s, start, end, after=0):
    a = s.index(start, after)
    b = s.index(end, a) + len(end)
    return s[a:b]
def macro(s, name):
    a = s.index("        .macro  " + name)
    b = s.index("        .endm\n", a) + len("        .endm\n")
    return s[a:b]
def build(src, variant):
    s = open(src).read()
    pan = seg(s, "        lea     COEF(%sp),%a4                     | above the saved MACSR", "        blt.w   2b\n")
    flt = seg(s, "        lea     hpf_state,%a0\n        lea     flt_coef,%a6\n        lea     RXBUF+8,%a2\n", "        bne.w   7b\n")
    a = s.index("        move.l  OUT_IDX,%d0")
    endm = "        bne.w   4b\n" if variant == "new" else "        bpl.w   4b\n"
    sm = seg(s, "        move.l  OUT_IDX,%d0", endm)
    bq = seg(s, "bq_run:\n", "        rts\n")
    macros = ""
    if variant == "new":
        macros = macro(s, "p1f") + macro(s, "bqf")
    gaintab = seg(s, "gaintab:\n", "        .endr\n")
    out = f"""
        .equ    P_TIMING, 0
        .equ    P_PROF, 0
        .equ    P_K, 11190
        .equ    FRAMES, 32
        .equ    RXSTRIDE, 48
        .equ    OUT_PRE, 48
        .equ    OUT_STRIDE, 64
        .equ    COEF, 64
        .equ    ENT, 132
        .equ    OFF_POLE, 0x7fff7fff
        .equ    RXBUF, m_rx
        .equ    OUT_RING, m_out
        .equ    OUT_IDX, m_idx
        .equ    SLOT_MAP, m_slot
        .equ    VCA_L, m_vca
        .equ    VCA_R, m_vca+16
        .equ    VOICE_OWNER, m_owner
        .equ    BLK_IN, m_rx
        .equ    BLK_IN_LEN, m_in_end-m_rx
        .equ    BLK_OUT_LEN, m_out_end-m_rx
{macros}
        .text
        .globl  _start
_start:
        move.l  #0xa0,%d0
        move.l  %d0,%macsr
        lea     -200(%sp),%sp
blk:
        lea     m_rx,%a0                          | read one block's inputs
        move.l  #BLK_IN_LEN,%d7
rd:     move.l  %a0,%d2
        move.l  %d7,%d3
        moveq   #0,%d1
        moveq   #3,%d0
        trap    #0
        tst.l   %d0
        ble.w   done
        add.l   %d0,%a0
        sub.l   %d0,%d7
        bne.s   rd
        move.l  m_d6,%d6
        moveq   #0,%d5
{pan}
        lea     COEF(%sp),%a0                     | the table out
        lea     m_coefo,%a1
        moveq   #(132+32)/4-1,%d0
c1:     move.l  (%a0)+,(%a1)+
        subq.l  #1,%d0
        bpl.s   c1
{flt}
        jsr     bq_run
{sm}
10:
        moveq   #4,%d0                            | write the block's outputs
        moveq   #1,%d1
        move.l  #m_rx,%d2
        move.l  #BLK_OUT_LEN,%d3
        trap    #0
        bra.w   blk
done:   moveq   #1,%d0
        moveq   #0,%d1
        trap    #0

{bq}
{gaintab}
        .data
        .align  4
m_rx:   .space  32*48+64
m_out:  .space  2048+64
m_idx:  .space  4
m_slot: .space  32
m_vca:  .space  32
m_owner: .space 8
        .space  4
hpf_mod: .space 48
shp_mod: .space 48
mod_frac: .space 12
frq_frac: .space 8
flt_coef: .space 96+8
bq_on:  .space  8
bq_coefs: .space 160
m_d6:   .space  4
m_in_end:
hpf_state: .space 64
bq_state: .space 128
m_coefo: .space 164
m_out_end:
m_regs: .space  64
pan_cache:
        .rept   8
        .long   0, -1, 0, 0
        .endr
"""
    return out
for v in ("old", "new"):
    open(f"h/{v}.s", "w").write(build(f"{v}.s", v))
