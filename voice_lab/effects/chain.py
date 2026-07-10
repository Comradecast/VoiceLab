from dataclasses import dataclass


@dataclass(frozen=True)
class EffectFailureStatus:
    effect_name: str
    message: str


@dataclass(frozen=True)
class EffectChainStatus:
    chain_order: tuple[str, ...]
    active_effects: tuple[str, ...]
    disabled_effects: tuple[str, ...]
    runtime_bypassed_effects: tuple[str, ...]
    failed_effects: tuple[str, ...]
    failures: tuple[EffectFailureStatus, ...]


class EffectChain:
    def __init__(self, effects=None, runtime_failure_handler=None):
        self.effects = list(effects or [])
        self._disabled = set()
        self._runtime_bypassed = set()
        self.last_errors = {}
        self._runtime_failure_handler = runtime_failure_handler

    def effect_names(self):
        return [self._effect_key(effect) for effect in self.effects]

    def status(self):
        chain_order = tuple(self.effect_names())
        disabled_effects = tuple(name for name in chain_order if name in self._disabled)
        runtime_bypassed_effects = tuple(name for name in chain_order if name in self._runtime_bypassed)
        failed_effects = tuple(name for name in chain_order if name in self.last_errors)
        active_effects = tuple(
            name
            for name in chain_order
            if name not in self._disabled and name not in self._runtime_bypassed
        )
        failures = tuple(
            EffectFailureStatus(name, str(self.last_errors[name]))
            for name in failed_effects
        )
        return EffectChainStatus(
            chain_order=chain_order,
            active_effects=active_effects,
            disabled_effects=disabled_effects,
            runtime_bypassed_effects=runtime_bypassed_effects,
            failed_effects=failed_effects,
            failures=failures,
        )

    def set_enabled(self, effect_name, enabled):
        if enabled:
            self._disabled.discard(effect_name)
        else:
            self._disabled.add(effect_name)

    def is_enabled(self, effect_name):
        return effect_name not in self._disabled and effect_name not in self._runtime_bypassed

    def bypassed_effects(self):
        return tuple(sorted(self._disabled | self._runtime_bypassed))

    def process(self, mono, frames, sample_rate, context=None):
        for effect in self.effects:
            effect_name = self._effect_key(effect)
            if not self.is_enabled(effect_name):
                continue
            try:
                mono = effect.process(mono, frames, sample_rate)
            except Exception as exc:
                self._runtime_bypassed.add(effect_name)
                self.last_errors[effect_name] = exc
                self._report_runtime_failure(effect_name, exc)
        return mono

    def _effect_key(self, effect):
        return getattr(effect, "name", effect.__class__.__name__)

    def _report_runtime_failure(self, effect_name, exc):
        if self._runtime_failure_handler is None:
            return
        try:
            self._runtime_failure_handler(effect_name, exc)
        except Exception:
            pass
