from voice_lab.plugins.loader import load_builtin_effect_chain


class PluginManager:
    def load_default_effect_chain(self, effect_state, runtime_failure_handler=None):
        return load_builtin_effect_chain(
            effect_state,
            runtime_failure_handler=runtime_failure_handler,
        )
