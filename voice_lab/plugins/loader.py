from voice_lab.effects import EffectChain, GainEffect, LowpassEffect, RobotEffect


def load_builtin_effects(effect_state):
    return [
        RobotEffect(lambda: effect_state.robot),
        LowpassEffect(lambda: effect_state.lowpass),
        GainEffect(lambda: effect_state.gain),
    ]


def load_builtin_effect_chain(effect_state, runtime_failure_handler=None):
    return EffectChain(
        load_builtin_effects(effect_state),
        runtime_failure_handler=runtime_failure_handler,
    )
