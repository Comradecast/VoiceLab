# Parametric EQ Foundation

Status: PASS. Luke completed practical live acceptance of the Parametric EQ
Foundation and corrected laboratory workflow.

Parametric EQ is the single audio-processing authority for manual voice-shaping
EQ. It precedes spectral-tilt execution so future spectral-tilt, character EQ,
or target-profile EQ intent can merge into one final EQ plan instead of adding
overlapping processors.

## Decision

- Add an isolated `--parametric-eq-lab` launch mode.
- Build the mode on the accepted M9.3 lab path and add one graph-first
  Parametric EQ tab. The original form-style five-row control surface was
  rejected before live DSP acceptance.
- Insert exactly one Parametric EQ stage after Experimental Pitch/Formant and
  before Robot. Limiter remains downstream.
- Use five fixed-role bands: Low Shelf, Low-Mid Peak, Mid Peak, Presence Peak,
  and High Shelf.
- Present those bands as five fixed draggable graph nodes with one selected-band
  inspector. M9.4 does not support arbitrary band creation or deletion.
- Use coarse graph interaction by default for practical audible audition:
  gain snaps to 0.5 dB during normal drag and 0.1 dB with Shift; frequency
  snaps to practical band-dependent Hz increments during normal drag and finer
  band-dependent increments with Shift; mouse-wheel Q uses 0.25 steps normally
  and 0.05 with Shift.
- Keep direct numeric inspector entry available for precise bounded values,
  with explicit fine stepping for finishing.
- Provide visible interaction feedback that names the band, current values, and
  Coarse/Fine mode, plus visible graph guidance for drag, wheel, Shift, and
  double-click reset.
- Make whole-EQ A/B comparison prominent through the existing local bypass
  authority. Bypass preserves EQ values and remains subordinate to global
  Bypass Effects.
- Use RBJ Audio EQ Cookbook biquad formulas implemented in the repository.
- Design coefficients in the service/controller path, outside the audio
  callback.
- Publish one immutable latest coefficient bank to the effect. The callback
  performs bounded scalar generation checks, bounded biquad processing, and a
  bounded dual-bank crossfade transition.
- Keep manual EQ values, local bypass, and EQ enable state session-only.
- Do not write settings, presets, calibration, lock, trim, or EQ files.

## Visualization Policy

- The Parametric EQ tab is graph-first: compact toolbar, large native Qt
  frequency-response canvas, selected-band inspector, and collapsed Diagnostics.
- The graph uses a logarithmic 20 Hz-20 kHz frequency axis, gain centered at
  0 dB, five fixed nodes, combined audible response curve, and subdued/disabled
  states for flat, local bypass, global bypass, and backend failure.
- ApplicationService exposes bounded immutable visualization snapshots derived
  from the same published coefficient bank used by DSP. The UI does not design
  coefficients, duplicate RBJ formulas, or import the EQ effect.
- Response snapshots use a fixed 256-point frequency grid and expose tuples, not
  NumPy arrays or mutable histories. Polling the snapshot does not create a new
  DSP generation.
- A bounded optional Post-EQ spectrum display uses a one-slot latest-frame
  mailbox and worker-side FFT. There is no FFT, UI work, queue accumulation, or
  history accumulation in the callback. Input/output/both analyzer modes remain
  deferred; M9.4 exposes Off and Post-EQ only.
- Engineering telemetry remains available in a collapsed Diagnostics panel.

## Band Ranges

- Low Shelf: 60-250 Hz, +/-6 dB, fixed slope/Q 1.0.
- Low-Mid Peak: 150-800 Hz, +/-6 dB, Q 0.3-6.0.
- Mid Peak: 500-2500 Hz, +/-6 dB, Q 0.3-6.0.
- Presence Peak: 1500-6000 Hz, +/-6 dB, Q 0.3-6.0.
- High Shelf: 4000-12000 Hz, +/-6 dB, fixed slope/Q 1.0, with applied
  frequency also limited to 45% of sample rate.

## Runtime Policy

- Flat all-zero-gain plans bypass the cascade internally and are neutral.
- Local EQ bypass is distinct from global Bypass Effects and subordinate to it.
- Invalid commands reject nonfinite, boolean, nonnumeric, missing, or unknown
  values before state mutation. Out-of-range finite frequency, gain, and Q
  values are clamped and reported.
- Runtime processing failure local-bypasses EQ and reports failed backend state
  without stopping the audio path.
- Active-to-flat, active-to-local-bypass, flat-to-active, and disable/enable
  changes use the same bounded dry/wet transition path as coefficient changes.
  The current wet bank and dry path crossfade for the configured transition
  duration, then the old path is retired and transition telemetry reports
  inactive.
- Flat-to-flat changes do not retain processor state or an active transition.
- New commands during a transition supersede the previous destination; the
  runtime keeps only one current path and one destination path, so UI updates do
  not accumulate a transition queue.
- Global Bypass Effects remains immediate and top-level. While global bypass is
  active, EQ audio is bypassed by the engine, audible transition progress is not
  claimed, and any bounded EQ transition is reported as pending. Releasing
  global bypass resumes processing the latest requested EQ state and settles the
  transition normally.
- Stop/reset clears active transition processors and runtime failure clears
  transition state into a truthful failed, locally bypassed snapshot.
- Stop/Start retains session EQ values and local enabled/bypass state; relaunch
  returns to flat disabled EQ.

## M9.3 Isolation

M9.3 continues to own calibration, suggestion, locked pitch/formant
transformation, pitch trim, formant trim, Adaptive Off/Continuous, and execution
enable. M9.4 owns only manual EQ values, EQ local enable/bypass, and final
applied EQ plan. EQ changes do not mutate calibration, suggestion, lock, trims,
or adaptive mode.

## Live Acceptance

Luke completed practical live acceptance after the workflow-truthfulness
correction. M9.4 is PASS.

Accepted UI results:

- Graph-first interface: PASS.
- Graph occupies the primary workspace: PASS.
- Five fixed draggable nodes are understandable: PASS.
- Selected-band inspector is usable: PASS.
- Diagnostics remain secondary/collapsed: PASS.
- Response curve is understandable: PASS.
- Post-EQ spectrum operates: PASS.
- Resizing remains usable: PASS.

Accepted accessibility results:

- Coarse graph movement is visible and usable: PASS.
- Shift fine-adjustment is available: PASS.
- Frequency snapping is understandable: PASS.
- Q coarse/fine adjustment works: PASS.
- Interaction overlay reports values and mode: PASS.
- Whole-EQ EQ ON/BYPASS comparison is prominent: PASS.
- Stored EQ returns after bypass: PASS.

Luke is partially deaf and initially found ordinary EQ changes difficult to
hear. Coarse interaction was added to improve audition accessibility; direct
numeric precision remains available; whole-EQ A/B remains the primary
comparison tool. This was an interaction/accessibility correction, not a DSP
defect.

Accepted DSP results:

- EQ reaches the active audio path: PASS.
- Individual and combined EQ plans operate: PASS.
- Flat EQ remains neutral: PASS.
- Reset EQ to Flat restores neutrality: PASS.
- Local bypass operates: PASS.
- Global bypass remains distinct: PASS.
- No pop, buzz, crackle, bad/growing delay, or obvious transition instability
  was observed: PASS.
- Transition telemetry settles truthfully: PASS.
- Added EQ algorithmic latency remains zero frames: PASS.

Workflow-truthfulness retest passed: production Pitch Shift is no longer
editable in chains where absent; Gain, Robot, and Lowpass remain available
where present; Suggested Plan, Stored Plan, and Applied Runtime are distinct;
Return Audio to Neutral neutralizes runtime while retaining the stored
transformation; Clear Stored Transformation clears lock and trims; target and
strength edits update suggestion only; explicit re-lock is required; Calibrate
& Lock is understandable; Soundboard is disabled in experimental labs; and
Parametric EQ remains independent from transformation lock authority.

The nasal/vowel artifact remains outside Parametric EQ. It occurs with
transformation active and EQ bypassed, worsens with negative formant movement,
and should be addressed by later pitch/formant naturalness work rather than
hidden with static EQ.

## Deferred Work

Planner `parametric_eq` remains unsupported in M9.4. Planner
`spectral_tilt_shaping` remains unsupported in M9.4. Future spectral-tilt
execution must map into this same EQ authority rather than adding a separate
audio effect.

Known non-blocking debt remains for pitch/formant naturalness, Lower/Weightier
pitch and formant direction decoupling, provisional diagnostic target profiles,
planner EQ, spectral-tilt execution, de-essing, breathiness synthesis, harmonic
enhancement, finished production feminine/deep-masculine characters,
Input/Output/Both spectrum modes, and optional future neural conversion.
