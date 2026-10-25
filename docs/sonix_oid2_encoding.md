# Sonix/OidProducer OID2 encoding: verified Python reproduction (2026-10-25)

**Status: A8S hardware and native NOB/NOD/NOS playback still unverified.**

## Open-source source and evidence

[jindroush/albituzka](https://github.com/jindroush/albituzka) is an MPL-2.0 project. Its [oid_png_generator.pl](https://github.com/jindroush/albituzka/blob/main/tools/oid_generator/oid_png_generator.pl) documents actual Sonix-related/Albi OID2 dots. Its [oid_table_extract.pl](https://github.com/jindroush/albituzka/blob/main/tools/oid_rawtable/oid_table_extract.pl) explains extraction of the **internal-to-raw 65536-entry lookup** from **OidProducer10.20.exe, MD5 78af7c4610995f7b98f35e3261e3dd19**. This table belongs to that upstream ecosystem/version; not verified on A8S. We do not ship or execute any OidProducer binary.

## Encoding facts (raw 16-bit OID, 600 DPI source)

- Basic OID2 primitive: 32 x 32 pixels = approximately 1.3547 mm.
- Seven fixed synchronization dots at (0,0),(8,0),(16,0),(24,0),(0,8),**(1,16)**,(0,24).
- A 3x3 grid of 9 displaced data dots; the first is a two-bit checksum; next eight contain the 16-bit raw OID in 2-bit groups, MSB-first.
- Each two-bit symbol: 00 maps to (+1,+1), 01 to (-1,+1), 10 to (-1,-1), 11 to (+1,-1), relative to the 8-pixel grid centers.
- Checksum: high = ((v>>2)^(v>>8)^(v>>12)^(v>>14)) & 1; low = (v^(v>>4)^(v>>6)^(v>>10)) & 1. Some Tiptoi variants modify it.
- At 1200 DPI, copy each dot into 2x2 pixels; **no interpolation**. Do not confuse printed raw OID with the internal pen index, sticker number or MP3 filename.

## Independent pixel-for-pixel result

Output was compared to previously generated PNGs from the upstream Albi/ODA workflow, **before** our Python reimplementation was written. All three 944x944 RGBA pixel arrays match exactly (0 different pixels):

| internal upstream index | printed raw OID | SHA256 of uncompressed RGBA pixels |
|---|---:|---|
|100|1331|`83f33b447826e68f11d388aaa03727535ee739ac16ac068c7b802fe241b7ef31`|
|101|1345|`693f68ac6040bdf4cdbe82f831cebc9a89bfd87cddf6dab395fb468589dd1c25`|
|102|1347|`2d09b30df30d22c6c574ff1d5c0c5e894ba2758477095a394ea2255268cc8be3`|

This proves digital OID2 artwork equivalence for these samples, **not** A8S optical compatibility.

## Commands

```powershell
python scripts/sonix_oid2.py render --raw-oid 1345 --dpi 1200 --width-mm 20 --height-mm 20 --out output/oid_raw_1345.png
python scripts/sonix_oid2.py verify --png output/oid_raw_1345.png --dpi 1200 --expected-raw-oid 1345
```

To parse the **published Perl literal** int2raw table without executing Perl:

```powershell
python scripts/sonix_oid2.py extract-table --upstream-source path/to/oid_png_generator.pl --out output/int2raw.json
```

For full experimental book, first run `ant_reader.py prepare` on `examples/oid_3code_smoke.json` and then:

```powershell
python scripts/make_sonix_oid2_binding.py --book-dir output/books/albi_oid2_smoke --assignment examples/sonix_oid2_smoke_assignment.json --out output/sonix_bindings
python book_assembly.py --book-dir output/books/albi_oid2_smoke --binding output/sonix_bindings/bindings.json --out output/experimental_sonix --allow-missing-audio
```

If actual audio was prepared, omit `--allow-missing-audio`. The vendor_handoff zip is NOT a native A8S installable book.

**P0 remaining:** confirm actual A8S sensor/firmware mode, valid book/index ranges, A8S-specific raw↔logical mapping and native audio pack through authorized test files, then physically scan printed OID2 pages with the A8S.

Sources: [Albi source](https://github.com/jindroush/albituzka); [Tiptoi decoder/checksum discussion](https://github.com/entropia/tip-toi-reveng/blob/master/oid-decoder.html); [Sonix OID family](https://www.sonix.com.tw/download/Consumer_OID.pdf).
