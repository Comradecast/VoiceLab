# M9.0 Passive Source Voice Analysis Lab

Status: PASS

## Decision

VoiceLab adds an explicit `main.py --voice-analysis-lab` mode to measure raw
microphone acoustics without changing audio. The lab is the measurement
foundation for future target-based character transformation, where a source
voice profile can later be compared with a target character profile to produce
a transformation plan.

Luke completed final live source-analysis acceptance for M9.0. The milestone
is accepted as PASS.

M9.0 is target-neutral. It measures acoustic properties only. It does not
classify the operator as male, female, masculine, feminine, young, old, or any
other identity category.

## Isolation

Normal launch remains unchanged and does not display Source Analysis. The
normal production chain remains:

1. High-Pass
2. Noise Gate
3. Compressor
4. Pitch Shift
5. Robot
6. Lowpass
7. Gain
8. Limiter
9. Mixer

The analyzer is not inserted into the effect chain. It does not control DSP
parameters, alter samples, persist profiles, change settings, change presets,
change routes, change devices, change meters, change soundboard behavior, or
change Signalsmith configuration.

## Observation Point

The source analyzer observes the raw `Capture.capture_block` frame in
`Router.main_callback`, before AudioEngine processing, Mixer, soundboard,
monitor routing, and virtual-output routing. This matches the conceptual raw
microphone point used by the Microphone Input meter.

Router performs only bounded publication to a passive tap. Router does not
calculate pitch, FFTs, spectral bands, formants, or profiles.

## Callback and Worker Boundary

Runtime flow:

Raw Capture -> `SourceAnalysisTap` -> `SourceVoiceAnalyzer` worker ->
immutable `VoiceAnalysisSnapshot` -> `ApplicationService` -> UI polling.

`SourceAnalysisTap` is a cadence-capped one-slot mailbox. It accepts at most
one pending frame for analysis, replaces stale pending input with newer input,
counts dropped replacements, and counts cadence-skipped frames separately.
The callback does not wait for analyzer work and does not perform analysis.

The worker owns all mutable analysis state. It builds a rolling analysis
window from accepted raw frames and publishes immutable scalar snapshots. No
NumPy arrays are exposed to ApplicationService or UI.

Live acceptance confirmed that raw microphone analysis occurs before DSP and
Mixer, analysis does not alter audio, callback publication uses a stable owned
copy, analysis runs outside the callback, mailbox capacity remains one frame,
and the rolling profile remains bounded to 240 scalar readings.

## Bounded State

- Analysis cadence: 20 Hz.
- Profile window: 12 seconds.
- Maximum retained readings: 240.
- Minimum voiced duration for profile readiness: 2.0 seconds.
- Stale snapshot timeout: 1.5 seconds.
- Profile percentiles: 10th and 90th F0 percentiles.
- Profile inclusion threshold: voiced frames with F0 confidence at least 0.50.

No unbounded queue, unbounded history, recording buffer, per-frame event queue,
callback file I/O, callback settings write, callback device query, callback Qt
access, or repetitive callback logging is introduced.

## Acoustic Measurements

Current readings include validity, voiced/unvoiced state, F0, F0 confidence,
RMS dBFS, peak dBFS, spectral tilt, chest ratio, low-mid ratio, presence
ratio, brightness ratio, sibilance ratio, likely-sibilant state, and
approximate resonance estimates where valid.

Rolling profiles include readiness, voiced-frame count, voiced duration,
voiced ratio, median F0, 10th/90th F0, pitch span in Hz and semitones, median
spectral tilt, median band ratios, stable resonance estimates where available,
and reliability.

Runtime status includes active state, worker-running state, snapshot age,
analyzed-frame count, dropped-frame count, skipped-frame count, invalid-frame
count, last failure, source sample rate, analysis cadence, analysis window
size, and retained-reading count.

## Algorithms

F0 uses deterministic normalized autocorrelation over a Hann-windowed rolling
analysis window with local-peak selection. The supported practical range is
60 Hz through 500 Hz. Silence, low-level input, broadband noise, fricative-like
noise, and insufficient-confidence frames are not reported as voiced. A pure
dominant tone above the supported range is rejected rather than reported as a
stable subharmonic.

Spectral analysis uses a Hann window and real FFT outside the callback. Band
ratios are normalized to total 80 Hz through 10 kHz speech-region energy and
truncate at Nyquist:

- Chest / low: 80-300 Hz.
- Low-mid: 300-900 Hz.
- Presence: 2-5 kHz.
- Brightness: 5-8 kHz.
- Sibilance: 5-10 kHz.

Spectral tilt is reported in dB as:

`10 * log10((2-8 kHz energy) / (80-900 Hz energy))`

Approximate resonance/formant output uses smoothed spectral-envelope peak
estimates for F1, F2, and F3 on suitable voiced frames. This is not a full LPC
or laboratory formant tracker. Silence, noisy consonants, and unreliable
frames can legitimately report unavailable resonance values.

Accepted measurement conclusion: the F0 estimator is accepted for practical
source profiling, spectral energy ratios are accepted as comparative
descriptors, `spectral_tilt_db` is an energy-ratio index rather than a fitted
dB-per-octave slope, and F1/F2/F3 estimates are weak descriptors only. They are
not approved as direct automatic control inputs.

## Reliability

Reliability states are based on measured conditions:

- collecting
- ready
- insufficient level
- insufficient voiced speech
- stale
- analyzer unavailable
- analyzer failure

Profile readiness requires sufficient reliable voiced speech. Silence and
unvoiced frames are excluded from pitch statistics and do not immediately erase
the last valid profile. Reset Source Analysis clears profile history and
readiness while preserving devices, routes, processing state, voice selection,
input-processing settings, bypass state, soundboard state, monitor state, and
volumes.

Analysis values are intentionally session-only. M9.0 creates no source-profile
file, exports no profile, keeps the bounded source profile only in memory, and
writes nothing to `settings.json` or `presets.json`. Reset, Stop/restart, and
relaunch begin fresh transient analysis state according to the implemented
lifecycle. No file was expected from Luke during live acceptance. Future
target-character processing will consume the live in-memory profile directly;
persistent analysis export remains deferred diagnostics scope.

## Future Use

Future feminine, masculine, deep masculine, giant, dark narrator, childlike,
elderly, creature, and synthetic character work can use this source profile as
one input to a target-neutral transformation-plan calculation. M9.0 does not
implement target profiles, adaptive pitch shifting, automatic formant shifting,
EQ correction, de-essing, synthesis, conversion, recording, exporting, or
automatic DSP control.

The analyzer is accepted as the source-profile foundation for feminine,
masculine, deep-masculine, giant, and other target profiles. The next epic is
the target-based character-transformation engine. The first target work must
support both feminine and deep-masculine directions.

## Final Acceptance

Final live M9.0 PASS results:

- Normal launch unchanged.
- Source Analysis absent from normal mode.
- Voice Analysis Lab launch.
- Application launches stopped.
- Start activates analysis.
- Stop/reset behavior.
- Repeated Start/Stop.
- Close/relaunch behavior.
- Audio transparency.
- No added audible latency.
- Metallic tail absent.
- Flutter absent.
- No crackle or new audible block boundaries.
- Normal speech F0 behavior appears plausible.
- Lower and higher voice changes are reflected.
- Quiet/loud speech behavior appears plausible.
- Sustained vowels collect stable data.
- Rapid speech continues updating.
- Silence/unvoiced behavior appears correct.
- Confidence behavior appears plausible.
- Rolling profile collects and reaches useful state.
- Median and pitch-range measurements appear plausible.
- Spectral descriptors respond plausibly.
- Analyzed/skipped/dropped status behaves normally.
- No UI freezing.
- No analyzer failure.
- Data collection appears fully functional in practical use.

Known non-blocking debt:

- Real-hardware close-while-processing was not separately isolated as a
  dedicated test beyond Luke's practical live use.
- Lock-free mailbox diagnostic counters may rarely undercount or lose a
  pending frame during a thread interleaving.
- Approximate resonance estimates remain weak descriptors.
- Lower-sample-rate Nyquist truncation lacks a dedicated focused test.

These are not known product failures and do not block M9.0 acceptance.
