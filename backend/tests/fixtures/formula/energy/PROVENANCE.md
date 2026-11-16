# gcsim energy sample (TASKS 14)

`national_energy_sample.json` is every `particle` event and every `draining energy` event of
one gcsim sample of `national_energy.txt`, nothing else, so the file stays small.

| | |
|---|---|
| gcsim | native build of `cmd/gcsim` at the pin, `b107b5dc5cb88977bed5270e5d83e64934730d4d` (`docs/CROSSVAL_gcsim.md`); the run's own `sim_version` is recorded in the file and asserted |
| command | `gcsim -c national_energy.txt -out out.json -sample sample.json` |
| sample seed | `924782146356144806` (in the file) |
| team | the owner's National team: Xiangling, Xingqiu, Bennett, Yelan |
| options | `ignore_burst_energy=true`, so every burst fires on its cooldown and the four rotations repeat identically; **no** `energy every` line, so every particle is a skill's |

Two choices in the config, each so the sample can be checked exactly rather than on average:

- **Bennett holds his skill at level 1** (`skill[hold=1]`), which always drops 3 particles
  (`internal/characters/bennett/skill.go:242`). His tap drops 2 or 3 at random (`:130-134`);
  the particle table carries its expectation, 2.25, and the estimate's per-cast field is where a
  hold is entered.
- **No weapon drops particles**: no Favonius, no Sacrificial.

Xiangling's ER in the run is 1.9594 (100 % base, The Catch R5's 45.9 % substat, Emblem's 20 %,
`er=0.3`). Her fourth drain reads **39.97176** banked energy: 1.9594 × 20.4, the 20.4 being
Bennett's 3 Pyro off field (5.4), Guoba's 4 Pyro with two caught on field and two off (9.6),
Xingqiu's 5 Hydro off field (3.0) and Yelan's 4 Hydro off field (2.4).
`tests/unit/test_formula_energy_gcsim_sample.py` and `npm run formula:verify` both assert it.

Re-derive: build gcsim at the pin (`go build ./cmd/gcsim` in a clone at the commit), run the
command above, and keep the `particle` and `draining energy` log entries.

# Summons, a Favonius proc and flat refunds (TASKS 14 follow-ups, DECISIONS §48)

Three more configs, run on the same native build at the pin:

| file | from | what it is |
|---|---|---|
| `summon_energy_sample.json` | `gcsim -c summon_energy.txt -out out.json -sample sample.json` (200 iterations; the sample's seed is in the file) | one sample: Raiden (Favonius Lance R3, `cr=0.3`, on field most of the time), Fischl, Kokomi, Zhongli, `ignore_burst_energy=true`, no drip. Every `particle` and `adding energy` event, every `draining energy`, the skill and burst casts, the summons' hits and the Favonius procs |
| `summon_rates.json` | `gcsim -c summon_rates_1.txt` and `summon_rates_2.txt`, 3000 iterations each, `-out` and `-sample` | each run's `total_source_energy` for its fourth member, who **never takes the field** (Xingqiu, then Bennett), so every particle reaches them at the off-field 0.6 and `mean / (0.6 × ER × value)` is the source's mean particle count; and the sample's hit counts, which are deterministic |

What the tests read from them (`tests/unit/test_formula_energy_summon_sample.py`):

- every particle event is `count × value × field × ER` (Favonius particles included: clear, 2);
- a Favonius proc's 3 clear particles land **100 frames** after the proc (gcsim's default particle
  delay), on whoever is active then: the wielder five times, and once Zhongli, who had taken the
  field inside the delay;
- Raiden's burst restores `2.4 × (1 + 0.006 × ⌊(ER − 1) × 100⌋)` flat, five times a burst, to
  every member;
- Oz hits 10 times a summon, the jellyfish 7 times a cast, the stele every 120 frames;
- over 3000 runs the particles per hit are 0.67 (Oz), 0.45 (Kuki's ring) and 0.67 (jellyfish) to
  within four standard errors; the stele sits under 0.5 a hit because its 1.5 s ICD eats a recast's
  first hit when the old stele ticked just before;
- Sara's Ambush drops 3, and her A4 gives every member `1.2 × 1.5` (her ER) flat.

`npm run formula:verify` holds `formula-energy.ts` to the same events (the Favonius particles
and Raiden's refund).

# Electro resonance and Yae Miko's totems (TASKS 14 refinements, DECISIONS §49)

Two more configs on the same native build at the pin (Go 1.27, `go build ./cmd/gcsim` in a
clone at `b107b5dc`), each `gcsim -c <file> -out out.json -sample sample.json`, keeping only the
events the tests read (`particles` for the sources named, the casts, and Yae's totem hits):

| file | from | what it is |
|---|---|---|
| `electro_res_sample.json` | `electro_res.txt` (seed `11851196483434702954` in the file) | Raiden, Fischl, Xingqiu, Bennett — a second Electro resonance team, bursts free so four rotations repeat. Every `electro-res` particle event |
| `yae_energy_sample.json` | `yae_energy.txt` (seed `17448528132612857946`) | Yae Miko with Fischl, Kokomi and Zhongli: one skill, left to expire, then three skills, left to expire. Every particle event from her totems, her casts, and every Sesshou Sakura hit |

What the tests read (`tests/unit/test_formula_energy_refinements_sample.py`), together with
`summon_energy_sample.json` above, whose 12 `electro-res` events gave Raiden 72.58 energy:

- each resonance particle is 1 Electro particle, `1 × value × field × ER`, distributed to every
  member at once; procs are never closer than 300 frames (the 5 s cooldown), and both teams
  proc 3 times a 25 s rotation, under the 5 the cooldown allows;
- Raiden's 72.58 is `3 procs × 4 rotations × 3 × field × ER` with her on-field share (8 of 12);
- Raiden, on field, caught all 24 of Oz's particles and 28 of her own Eye's 36 on field;
- Yae's particles land one every 176 frames — a totem's cadence — with one totem and with
  three, 8 for a totem set at full length either way, while three totems strike three times
  as often: the shared ICD.

`npm run formula:verify` holds `formula-energy.ts` to the same events.

# The small calls: Venti's absorbed element, constellation refunds, the drip (TASKS 14, DECISIONS §50)

Two more configs on the same native build at the pin (Go 1.27, `go build ./cmd/gcsim` in a
checkout at `b107b5dc`), each `gcsim -c <file> -out out.json -sample sample.json` (20 iterations;
the sample's seed is in the file), keeping every `particle`, `adding energy` and `draining energy`
event, the casts, and Venti's `infusion check` lines:

| file | from | what it is |
|---|---|---|
| `venti_cons_energy_sample.json` | `venti_cons_energy.txt` (seed `15325029959068778551`) | Venti (C0, A4), Xiangling, Kaeya C6, Thoma C4, bursts free, **with** the drip (`energy every interval=480,720 amount=1`): Venti's absorption and both halves of his A4, Kaeya's and Thoma's burst refunds, and every drip particle |
| `klee_cons_energy_sample.json` | `klee_cons_energy.txt` (seed `2622578390594857073`) | Klee C6, Diona C1, Furina C4, Barbara C1: Klee's 3 to every other member three times a burst, Diona's 15 at her burst's end, Furina's 4 under a 5 s ICD, Barbara's 1 every 10 s |

What the tests read (`tests/unit/test_formula_energy_small_calls_sample.py`, and
`npm run formula:verify` for the same totals):

- Venti's burst absorbs **Pyro** each time — the first of gcsim's order (Pyro, Hydro, Electro,
  Cryo) that a teammate carries, the browser's default — and his A4 gives 15 to himself and 15
  to each Pyro member (Xiangling, Thoma), none to Kaeya;
- Kaeya's C6 and Thoma's C4 are 15 once a burst, Diona's C1 15 once a burst; Klee's C6 is 3 to
  each other member three times a burst and nothing to Klee;
- Furina's C4 procs never come inside 300 frames; the Salon's hits land on a grid, so they come
  about every 5.4 s, under the per-second form's one per 5 s (an upper bound, stated);
- Barbara's C1 is 1 every 600 frames from frame 601, for the whole fight;
- each drip `drop` reaches every member at once, a clear particle, `2 × field × ER`, exactly one
  receiver on field — which is why an on-field subject catches it on field.
