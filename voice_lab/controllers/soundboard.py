from voice_lab.app.soundboard_assets import list_sound_files, load_sound


class SoundboardController:
    def __init__(self, commands=None):
        self.commands = commands

    def set_commands(self, commands):
        self.commands = commands

    def trigger_file(self, filename):
        if self.commands is None:
            return None
        return self.commands.play_sound_file(filename)

    def trigger_index(self, index):
        if self.commands is None:
            return None
        return self.commands.play_sound_by_index(index)
