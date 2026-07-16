# Higher / Brighter Naturalness

Status: PROVISIONAL. M9.6 automated implementation and regression verification
are complete; live Natural Bright acceptance is pending.

## Context

Before M9.6, the canonical `diagnostic-higher-brighter` target used an
absolute-F0 pitch strategy with target median F0 `220 Hz` and restrained fixed
formant `+1.2 st`.

For a `120 Hz` source at `100%`, that formula requested:

```text
10.493629 st = 12 * log2(220 / 120)
```

The planner then applied the existing `+8.0 st` pitch clamp. Lower sources hit
the clamp earlier, while higher sources could request much less movement or
even downward movement. That made strength interpolation source-dependent and
could push the diagnostic target toward chipmunk-like or helium-like behavior.

## Decision

Keep canonical target ID `diagnostic-higher-brighter`, but make its canonical
semantics Natural Bright:

- display name: Natural Bright Reference;
- pitch strategy: relative shift;
- full-strength pitch: approximately `+3.5 st`;
- formant strategy: restrained fixed positive shift;
- full-strength formant: approximately `+1.0 st`;
- no absolute target F0 forcing;
- no finished feminine-character claim.

Add `diagnostic-small-cartoon` as the explicit stylized upward comparison
target:

- display name: Small / Cartoon Reference;
- pitch strategy: relative shift;
- full-strength pitch: approximately `+6.0 st`;
- formant strategy: size-coupled stylization;
- full-strength formant: approximately `+2.0 st`;
- warning at nonzero strength that it may sound chipmunk-like, thin, nasal, or
  sharply sibilant.

Visible target order is:

1. Neutral
2. Natural Bright
3. Natural Deep
4. Small / Cartoon
5. Large / Cavernous

## Compatibility

The legacy `higher_brighter` lookup resolves to canonical
`diagnostic-higher-brighter` Natural Bright semantics. The new
`natural_bright` lookup resolves to the same target. Stored plans expose one
canonical target identity, no duplicate Natural Bright target appears, and the
alias does not create a dirty-state mismatch.

The old absolute-F0 behavior is retained only as documented historical audit
evidence. It is not an active visible natural target.

## Manual Trim

Manual trim remains additive operator authority over the immutable planner
base. For a locked Natural Bright plan near `+3.5 st` pitch and `+1.0 st`
formant, formant trim can compare final formant values:

- `-1.0 st` trim -> `0.0 st` final formant;
- `-0.5 st` trim -> `+0.5 st` final formant;
- `0.0 st` trim -> `+1.0 st` final formant;
- `+0.5 st` trim -> `+1.5 st` final formant;
- `+1.0 st` trim -> `+2.0 st` final formant.

The base plan is not mutated, manual formant trim remains `+/-2.0 st`, and the
runtime formant safety clamp remains `+/-2.0 st`.

## Non-Changes

M9.6 does not add a pitch processor, formant processor, Signalsmith stage,
Signalsmith buffering change, latency change, de-essing, breathiness synthesis,
harmonic enhancement, spectral-tilt execution, planner-driven Parametric EQ,
static EQ compensation, phoneme or speech recognition, gender/age/identity or
speaker classification, neural conversion, target persistence, plan
persistence, settings schema change, presets schema change, production
character replacement, Continuous default change, or implicit stored-plan
mutation.

Natural Deep and Large / Cavernous values are unchanged from M9.5.

Planner `parametric_eq` and `spectral_tilt_shaping` remain unsupported.

## Live Acceptance Pending

Natural Bright is accepted only provisionally until Luke confirms live that it
sounds more natural than the old absolute-F0 behavior, does not primarily sound
chipmunk-like or helium-like, remains distinct from Small / Cartoon, preserves
usable sibilants and recognizable vowels, and does not regress stability or the
calibration/lock workflow.

M9.6 also requires unified workflow live acceptance. The normal Natural Bright
test path now starts on the `Transform` page and uses Apply Transformation /
Apply Changes instead of requiring the user to move across Source Analysis,
Target Planner, Calibrate & Lock, Plan Execution, and Parametric EQ tabs.
