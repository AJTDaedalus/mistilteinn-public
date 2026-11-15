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
