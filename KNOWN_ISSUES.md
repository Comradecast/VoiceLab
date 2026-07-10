# VoiceLab Known Issues

This document tracks observed runtime issues that should not derail current architecture milestones.

## Soundboard

### Double-trigger / Two-step Playback

Observed:

- Soundboard sounds appear to play in two stages rather than immediately.

Status:

- Historical / not reproduced during final RC1 hardware acceptance.

Priority:

- Low.

Notes:

- Final M5.6 RC1 hardware acceptance found soundboard playback passing.
- The former two-stage behavior was not reproduced during the final hardware
  smoke session.
- Keep this as a historical observation, not an active RC1 blocker. Reopen only
  if the behavior becomes reproducible again.

## Telemetry / UI

### Backend Telemetry Not Visible In UI

Observed:

- Final M5.6 manual hardware acceptance could not verify backend telemetry,
  fallback warnings, or initial telemetry through the UI because telemetry is
  not currently visible in the application.
- Automated verification confirmed Signalsmith `available=True`, backend
  `signalsmith`, status `active`, telemetry readability, and no fallback active.

Status:

- Deferred usability/telemetry-visibility work.

Priority:

- Low for RC1.

Notes:

- This does not block RC1 because backend telemetry is readable through the
  automated path.
- The broader telemetry visibility decision remains tracked in
  `decision_queue/telemetry-visibility.md`.

## Pitch Shift

### Pedalboard Streaming Continuity Limitation - Closed

Observed:

- `pedalboard.PitchShift.process(..., reset=False)` returned empty output for small real-time blocks during offline inspection.
- Larger `reset=False` windows eventually returned output buffers containing silence in deterministic offline experiments.
- VoiceLab therefore uses an effect-internal streaming adapter with bounded FIFOs and 2048-frame processing windows. The adapter returns deterministic silence while priming, always returns the callback frame count, and resets/re-primes only when pitch changes.
- Live testing reported two separate symptoms: metallic/robotic coloration during active speech, and a brief electronic buzzing/ringing tail after speech stops.
- Offline diagnostics confirmed `RobotEffect` at amount `0` is bit-identical passthrough and is not responsible for pitch coloration.
- PitchShift alone produced tail energy after voiced input transitioned to silence before the adapter silence-transition fix. Direct Pedalboard processing of a half-voiced, half-silent window also produced residual tail energy, indicating an algorithmic component in the backend.
- The pitch adapter now flushes buffered output and resets the backend once when exact digital silence is received after voiced input, preventing stale FIFO samples from being replayed.
- Live testing found the earlier 8192-frame window caused distracting monitor delay. Offline latency diagnostics selected 2048 frames as the smallest tested window that substantially improved callback-boundary continuity versus 1024 while preserving bounded exact-silence tail behavior.

Status:

- Automated adapter checks pass.
- Exact-zero tail diagnostics pass for sine, speech-like synthetic audio, and impulse input.
- Final RC1 hardware listening test passed for the canonical Signalsmith path.

Priority:

- Medium.

Notes:

- Pitch `0` bypasses processing and is effectively neutral.
- Current callback block size is 1024 frames at 48 kHz.
- Current pitch window is 2048 frames. The processing window duration is about 42.67 ms, with about 21.33 ms first-output buffering delay before routing/device latency.
- Input FIFO target is less than one processing window; output FIFO target is one callback block after each processed window.
- The monitor path uses a separate output stream. Its handoff queue is now limited to the latest frame only, preventing avoidable multi-block monitor backlog; the separate stream can still contribute an inherent device/scheduling block.
- Pitch changes reset and re-prime the adapter, which may cause a brief silence or artifact.
- Exact digital silence now settles to zero immediately in offline tests; live microphone noise may not be exact digital silence, so manual testing must confirm whether the reported tail is eliminated in real routing.
- Non-zero pitch may still produce metallic/robotic coloration or discontinuities at processing-window boundaries because the installed Pedalboard backend did not provide usable continuous `reset=False` streaming output.
- This keeps the M5.0 demonstrator bounded and callback-safe, but RC1 hardening should evaluate latency, crackle, and continuity under real microphone routing and consider a streaming-capable pitch backend if quality is unacceptable.
- Follow-up live testing found exactly that tradeoff: 8192-frame Pedalboard buffering had acceptable continuity but unacceptable monitor latency, while 2048-frame buffering improved latency but brought flutter/choppiness back. Pedalboard is therefore unsuitable as the primary real-time pitch backend unless new evidence disproves this.
- M5.3 Signalsmith live hardware testing closed the Pedalboard continuity/tail issue for the canonical pitch path. The native Signalsmith backend loaded successfully, the metallic/electrical tail is gone, and flutter/choppiness is gone.
- M5.6 final RC1 hardware acceptance reconfirmed metallic tail absent,
  flutter/choppiness absent, and latency acceptable.

Window diagnostics at 48 kHz with 1024-frame callbacks:

| Pitch window | Processing window | First-output buffering delay | Output FIFO target | Offline result |
| --- | --- | --- | --- | --- |
| 1024 | 21.33 ms | 0 ms | 0 frames | Lowest latency but largest callback-boundary jumps; likely chopped. |
| 2048 | 42.67 ms | 21.33 ms | 1024 frames | Selected. Much lower median boundary jump than 1024 with bounded exact-silence tail. |
| 4096 | 85.33 ms | 64.00 ms | 3072 frames | Smoother offline than 2048 but adds substantially more latency. |
| 8192 | 170.67 ms | 149.33 ms | 7168 frames | Smoothest tested offline but live monitor delay was distracting. |

Status:

- Closed for the canonical Signalsmith backend.
- Pedalboard remains fallback/diagnostic only.

### Large Pitch Shifts Are Synthetic

Observed:

- `+/-4` semitones sounds good and close to the intended product direction.
- `+/-8` semitones is usable but clearly pitch-modulated.
- `+/-12` semitones is intentionally extreme.

Status:

- Expected limitation.

Priority:

- Low.

Notes:

- Recommended normal demonstration preset range is around `+/-4` semitones.
- Larger shifts should be treated as obvious transformation effects, not natural identity conversion.

### Sung Notes Can Flatten on Some Transitions

Observed:

- Some sung notes, bends, or transitions may sound flattened on the Signalsmith
  backend.

Status:

- Deferred product-quality debt.

Priority:

- Low for RC1.

Notes:

- This does not block RC1 because spoken voice quality and normal `+/-4`
  semitone preset guidance passed live hardware testing.
- Do not change the proven Signalsmith DSP configuration during M5.4 to address
  this issue.
