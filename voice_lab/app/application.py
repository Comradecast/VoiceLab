from PySide6.QtWidgets import QApplication

from voice_lab.app.lifecycle import ApplicationLifecycle


def run():
    from voice_lab.ui.main_window import App

    app = QApplication([])
    lifecycle = ApplicationLifecycle()
    service = lifecycle.startup()
    window = App(service, on_close=lifecycle.shutdown)
    window.resize(720, 720)
    window.show()
    lifecycle.start_controllers()
    app.aboutToQuit.connect(lifecycle.shutdown)
    return app.exec()
