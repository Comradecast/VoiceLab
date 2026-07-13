from PySide6.QtWidgets import QApplication

from voice_lab.app.lifecycle import ApplicationLifecycle
from voice_lab.app.service import ApplicationService


def run(formant_lab=False, voice_analysis_lab=False):
    from voice_lab.ui.main_window import App

    app = QApplication([])
    lifecycle = ApplicationLifecycle(
        service_factory=lambda **kwargs: ApplicationService(
            **kwargs,
            formant_lab=formant_lab,
            voice_analysis_lab=voice_analysis_lab,
        )
    )
    service = lifecycle.startup()
    window = App(service, on_close=lifecycle.shutdown)
    window.resize(720, 720)
    window.show()
    lifecycle.start_controllers()
    app.aboutToQuit.connect(lifecycle.shutdown)
    return app.exec()
