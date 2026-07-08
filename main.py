from PySide6.QtWidgets import QApplication
from voice_modulator.ui import App

app = QApplication([])
w = App()
w.resize(720, 720)
w.show()
app.exec()
