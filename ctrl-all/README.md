# ctrl-all

Port of rytm-mods-src `mods/0014-ctrl-all` (MrScruff; hardware-verified there).

Hold TRK and turn a knob on a sound page (SYNTH, SAMPLE, FILTER, AMP, LFO) or the TRIG page: the
same step goes to that parameter on all twelve sound tracks, so their differences are kept and each
track stops at its own limits. On the SYNTH page each track takes its own machine's parameter in the
same parameter slot (the machine's synth parameters in MIDI CC order, CC 16..23), within that
parameter's range; a track whose machine has none there is left alone. The slot is not always the
knob's place on the screen: with BD HARD on one track and SD HARD on another, Hold Time moves Sweep
Depth (both CC 19) and Sweep Time moves Tick Level (both CC 20). FILTER TYP is the exception: the selected track's type changes as usual and every other
track is set to the same type. Stock behaviour (selected track only) with the FX
track selected, while a trig key is held (so parameter locks stay on one track), and on FX or global
pages.

## How it hooks

One site, the same as rytm-mods' detour: `param_apply_delta_dispatch`, 0x400378c2, in
param_apply_delta after the track lookup. The 6 stock bytes (`move.l %a2@,%a0; pea -1`) become
`jmp ctrl_all_gate`. The gate checks FX track, TRK held, no trig key held and a sound or TRIG set; if
all pass it calls each track's set's own delta handler for tracks 0..11 and returns through
param_apply_delta's epilogue, otherwise it re-emits the two instructions and resumes at 0x400378c8.

In rytm-mods this address is the end of a chain: 0002, 0003, 0004 and 0013 detour the instructions
just before it (0x400378a6..0x400378bc), so the parameters those mods add stay single-track. Here
those are separate sites owned by their own mods; none of them is ported yet.

In 1.1 (rytm-mods-src 76ae299, MrScruff's update): the SYNTH page by each machine's own parameter
(`sound_param_id_for_index`) instead of the selected machine's range, and FILTER TYP under TRK
(`param_set_value` for the other tracks). voice-dac 1.1 handles its own DAC FILTER page the same way,
before this gate.

## Changes from rytm-mods

- The stub's code is unchanged. `ctrl_all_gate` is `.globl`; nothing else is.
- It runs from the elemod DDR area instead of cave13 (0x40029838).
- Symbols come from `../include/ar2-1.73.inc`.

## Test (on a unit)

1. FILTER page: note FRQ on two tracks. On one, hold TRK and turn FRQ: the other track's FRQ moves by
   the same amount. The FILTER, AMP, LFO, SAMPLE and TRIG pages do not depend on the machine.
2. SYNTH page: give two tracks different machines, hold TRK and turn a SYNTH knob: each moves its own
   parameter in the same slot (MIDI CC order), within its own range; a track whose machine has none
   there stays.
3. FILTER page: hold TRK and turn TYP: every track takes the type the selected track reaches.
4. With the FX track selected, or with a trig key held, only the selected track changes.

## Results so far

1.1 (MrScruff's update): `.run` 420 B, 1 site, no relocations; `tools/verify_port.py` against
rytm-mods-src 76ae299's default build: the re-assembly equals its caves (.text 0x40029838+118, .typ
0x40029950+306) and all 4 labels match.

- Hardware, OS 1.74 (2026-10-18), core-ar2 with filter-hz, ctrl-all, env-reset-amp, slice-loop,
  main-rms, lfo-rnd, comp-preview and kit-ab: tests 1, 3 and 4 as described. Test 2 with BD HARD
  (track 1) and SD HARD (track 2): Tune, Decay and Level follow each other, and the rest pair by
  slot as above (Sweep Time with Tick Level, Snap Amount with Noise Decay, Waveform with Noise
  Level, Hold Time with Sweep Depth, Tick Level with Sweep Time).
- rytm-emu (c5732f0), the same build for 1.73 and 1.74: FILTER, TYP and SYNTH page screens
  pixel-identical between the two.

1.0:

- Hardware: on an Analog Rytm MKII, 2026-10-13, in a build of core-ar2 with filter-hz, ctrl-all,
  env-reset-amp and slice-loop: works on the FILTER page (FRQ) and on the SYNTH page between two
  tracks with the same machine (XT CLASSIC on LT and MT).
- `.run` 172 B, 1 site, no relocations; lint OK; links with core-ar2 0.1.
- The 170 B of code (plus 2 B alignment) linked into the image are byte-identical to the stub in
  rytm-mods-src's default build (cave13, 0x40029838). The site reads `jmp 0x47be01cc` in place of
  `jmp 0x40029838`.
- rytm-emu (3c4c42c), the four-mod build above: with TRK held, 14 turn events reach the site; the gate takes the
  all-tracks path every time (0 resumes at 0x400378c8) and calls the sound set's delta handler
  (0x400a95dc) 168 times = 14 x 12 tracks; stock calls it 14 times. The selected track's value
  moves exactly as on stock, and the screens are pixel-identical to rytm-mods' own build.
