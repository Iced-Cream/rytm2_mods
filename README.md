# rytm2_mods

[rytm-mods-src](https://github.com/Iced-Cream/rytm-mods-src)'s Analog Rytm MKII OS 1.73 mods
(MrScruff, published with permission), ported one by one to the **elemod** format so they
link with [elekloader](https://github.com/irpina/elekloader)'s `core-ar2` and with each other,
instead of being patched into code caves at fixed addresses.

No firmware is included: no OS files, sections, dumps or built `.syx`/`.elemod` files. The
mods name firmware routines by address only (`include/ar2-1.73.inc`), and their `mod.json`
sites carry the stock instruction bytes they replace, as elekloader's own mods do.

## Layout

| path | what |
|---|---|
| `include/ar2-1.73.inc` | every main-OS symbol of rytm-mods-src's `re/symbols.toml` as an absolute `.equ` (generated, 275 symbols) |
| `shared/shared.s` | rytm-mods-src's `0000-shared` runtime, included into each mod that uses it |
| `<mod>/` | one elemod mod: `mod.json`, its source, `README.md` |
| `tools/gen_symbols.py` | regenerates the include from a rytm-mods-src checkout |
| `tools/port_mod.py` | ports one rytm-mods mod mechanically (source and `mod.json`; the README is by hand) |
| `tools/verify_port.py` | checks a port against rytm-mods' own build, label by label (re-assembles the original, then compares disassembly with every address named) |

## How a rytm-mods mod becomes an elemod mod

| rytm-mods | here |
|---|---|
| a `[[detour]]` in `registry/allocations.toml` (addr, `expect` bytes, entry) | a `sites` entry: `{"addr", "stock": <the whole instructions displaced>, "op": "jmp", "target": <entry>}`; where the 6-byte jmp lands across an instruction the stub re-emits, the site takes it whole |
| a `[[patch]]` with `replace` | a `bytes` site (`"kind": "code"` in .text), widened to whole instructions |
| a `[[patch]]` with `from_symbol`, in a data table | a `ptr` site |
| a `[[patch]]` with `from_symbol`, the address operand of a `jsr`/`lea`/`move.l #` | a `keep2` site: the opcode word kept, the address the mod's (any other instruction: a `bytes` code site with an `abs32` reloc) |
| a stub at a fixed cave address, or split over several caves by `.section` | ordinary code, placed by the linker in the 128 KB DDR area: every section becomes `.text` → `.run` |
| state kept in a cave | stays with the code in `.run` (DDR is RAM) |
| a `gate` on a claim | applied with the default build's params |
| `build/symbols.inc` | `include/ar2-1.73.inc` |
| `build/shared.inc` + mod 0000 | `.include "../shared/shared.s"` in the mod itself |
| build `params` | fixed at the default build's values |

Rules that matter (elekloader docs/ADAPTING.md): only labels that a site or event names are
`.globl`, and they start with the mod's id; everything else stays local, so two mods never
export the same name. `port_mod.py` adds a prefixed global alias beside each such label, so the
stub's own references stay local and assemble as they did in rytm-mods (the hand-ported
slice-loop and env-reset-amp rename their entry label instead). A site covers whole stock instructions; the stub re-emits what it
displaced, exactly as in rytm-mods. Two mods may never patch the same bytes.

0000-shared is not a mod here: its ~234 bytes are assembled into each mod that calls it
(velocity-humanise, lfo-rnd and voice-dac), so every mod stands alone. velocity-humanise does
need euclid-accents (its amount lives in bits only euclid-accents saves), and says so in
`requires`; the linker refuses it alone.

The gate chain: euclid-accents, velocity-humanise, lfo-rnd, voice-dac and ctrl-all detour
consecutive instructions of param_apply_delta (0x400378a6..0x400378c2) and euclid-accents,
velocity-humanise, lfo-rnd and voice-dac those of param_value_text (0x400a85e0..0x400a85f8).
Each is its own site, and each stub rejoins at the next instruction, which is the next mod's
jmp when that mod is linked and stock when it is not - as in rytm-mods.

## Build

You need:

- an [elekloader](https://github.com/irpina/elekloader) checkout at `main` (Analog Rytm MKII
  support and `core-ar2` arrived in irpina/elekloader#89) and the Python 3 it asks for;
- ColdFire binutils on `PATH` (`m68k-linux-gnu-as` and `-ld`; on Debian or Ubuntu,
  `apt install binutils-m68k-linux-gnu`);
- your own copy of Elektron's stock Analog Rytm MKII OS 1.73 `.syx`. It is never part of
  this repository or of anything built from it.

```bash
EL=path/to/elekloader                        # the elekloader checkout
R2=path/to/rytm2_mods                        # this repository
STOCK=path/to/Analog-Rytm_MKII_OS1.73.syx    # your stock OS file
cd "$EL"
python3 -m elekloader.sdk.build mods/core-ar2 --stock "$STOCK"
MODS="filter-hz ctrl-all env-reset-amp slice-loop euclid-accents velocity-humanise lfo-rnd
      comp-preview main-rms kit-ab voice-dac"
ARGS=""
for m in $MODS; do
  python3 -m elekloader.sdk.build "$R2/$m" --stock "$STOCK"
  ARGS="$ARGS --mod $R2/$m/out/$m-1.0.elemod"
done
python3 -m elekloader.patch --stock "$STOCK" --mod mods/core-ar2/out/core-0.1.elemod $ARGS \
    --out rytm-mods.syx --version R2AL
```

Leave out any mod you don't want from `MODS`, but keep euclid-accents whenever
velocity-humanise is in: elekloader refuses velocity-humanise without it. `elekloader.patch`
checks that the selected mods combine before it writes anything. `--version` is the
four characters the unit shows as its OS version. The result is your own firmware file:
keep it, and the `out/` build folders, out of git and out of any upload.

## Status

| rytm-mods-src | here | source status | port |
|---|---|---|---|
| 0000-shared | `shared/shared.s` | built | ported (included by velocity-humanise, lfo-rnd, voice-dac) |
| 0008-filter-hz | `filter-hz/` | hardware-verified | matches label by label; **confirmed on a unit** |
| 0012-slice-loop | `slice-loop/` | hardware-verified | matches label by label; **confirmed on a unit** |
| 0014-ctrl-all | `ctrl-all/` | hardware-verified | matches label by label; **confirmed on a unit** |
| 0015-env-reset-amp | `env-reset-amp/` | hardware-verified | bit probe left out; matches label by label; **confirmed on a unit** |
| 0002-euclid-accents | `euclid-accents/` | hardware-verified | matches label by label; **confirmed on a unit** |
| 0003-velocity-humanise | `velocity-humanise/` | built (MANUAL: verified) | needs euclid-accents; matches label by label; **confirmed on a unit** |
| 0004-lfo-rnd | `lfo-rnd/` | built (MANUAL: verified) | matches label by label; **confirmed on a unit** |
| 0006-comp-preview | `comp-preview/` | hardware-verified | matches label by label; **confirmed on a unit** |
| 0009-main-rms | `main-rms/` | built (MANUAL: display checked on the device) | matches label by label; **confirmed on a unit** |
| 0010-kit-ab | `kit-ab/` | hardware-verified | matches label by label; **confirmed on a unit** |
| 0013-voice-dac | `voice-dac/` | hardware-verified | default build only (no timing, prof, burn or dbg); matches label by label; **confirmed on a unit** |

Every mod on rytm-mods-src main is now ported. "Matches label by label": `tools/verify_port.py`
re-assembles rytm-mods' own code, checks it equals rytm-mods-src's default build ("T2"), then
compares each label's instructions with the port's, every address named by its label. For all
eleven, in the full build (core-ar2 with every port, as in Build above): every byte it changes
in the OS is inside one of the ports' sites, every one of those sites is also patched by
rytm-mods' default build (T2), and the `bytes` sites write T2's bytes exactly. rytm-mods'
diagnostic builds (its non-default params and the claims they gate) are not ported.

## Licence

GPL-2.0, as rytm-mods-src (`LICENSE`). The mods are MrScruff's work; the elemod ports keep his
code and note every change.
