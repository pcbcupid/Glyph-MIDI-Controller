"""Run the key event handler without CircuitPython hardware: python -m unittest discover."""

import ast
from pathlib import Path
from types import SimpleNamespace
import time
import unittest


CODE = Path(__file__).parents[1] / "glyph_mini_2040_midi_keyset" / "code.py"
tree = ast.parse(CODE.read_text(encoding="utf-8"))
chord_functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name in ("guitar_chord", "chord_name")]
chord_constants = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id in
                           ("GUITAR_OPEN_STRINGS", "CHORD_ROOTS", "CHORD_SHAPES", "OPEN_CHORDS")
                           for target in node.targets)]
CHORD_HELPERS = compile(ast.Module(body=chord_constants + chord_functions, type_ignores=[]),
                        str(CODE), "exec")
loop = next(node for node in tree.body if isinstance(node, ast.While))
handler = next(node for node in loop.body if isinstance(node, ast.If)
               and isinstance(node.test, ast.Name) and node.test.id == "event")
RUN_HANDLER = compile(ast.Module(body=[handler], type_ignores=[]), str(CODE), "exec")


class Message:
    def __init__(self, note, velocity):
        self.note = note
        self.velocity = velocity


class Midi:
    def __init__(self):
        self.sent = []

    def send(self, message, channel=None):
        self.sent.append((type(message).__name__, message.note, channel))


class KeyChannelTest(unittest.TestCase):
    def test_chord_catalog_maps_to_guitar_midi_range(self):
        env = {}
        exec(CHORD_HELPERS, env)
        for root in range(12):
            for shape in range(len(env["CHORD_SHAPES"])):
                notes = env["guitar_chord"](root, shape)
                self.assertTrue(3 <= len(notes) <= 6)
                self.assertTrue(all(40 <= note <= 88 for note in notes))
                self.assertEqual(len(notes), len(set(notes)))
        self.assertEqual(env["guitar_chord"](0, 0), (48, 52, 55, 60, 64))
        self.assertEqual(env["guitar_chord"](9, 1), (45, 52, 57, 60, 64))

    def test_custom_preset_has_no_capo_pitches(self):
        env = {}
        exec(CHORD_HELPERS, env)
        settings_node = next(node for node in tree.body if isinstance(node, ast.Assign)
                             and any(isinstance(target, ast.Name) and target.id == "control_settings"
                                     for target in node.targets))
        settings = ast.literal_eval(settings_node.value)["keys"]
        names = [env["chord_name"](key["chord_root"], key["chord_shape"])
                 for key in settings]
        self.assertEqual(names, ["C#m", "B", "A", "B", "C#m", "B"])
        self.assertEqual(env["guitar_chord"](1, 1), (49, 56, 61, 64, 68))
        self.assertEqual(env["guitar_chord"](11, 0), (47, 54, 59, 63, 66))
        self.assertEqual(env["guitar_chord"](9, 0), (45, 52, 57, 61, 64))

    def test_release_uses_note_and_channel_from_press(self):
        midi = Midi()
        settings = [{"note": 61, "velocity": 120, "channel": 5} for _ in range(6)]
        env = {
            "event": SimpleNamespace(key_number=0, pressed=True, released=False),
            "control_settings": {"keys": settings},
            "POT_C_INSTRUMENTS": False,
            "current_instrument": -1,
            "INSTRUMENTS": [],
            "DRUM_NOTES": [36, 38, 42, 46, 49, 51],
            "DRUM_CHANNEL": 9,
            "MIDI_NOTE_NAMES": [str(i) for i in range(128)],
            "held_keys": [None] * 6,
            "active_notes": {},
            "chord_mode": False,
            "key_panels": [SimpleNamespace(fill=None) for _ in range(6)],
            "keynote_labels": [SimpleNamespace(color=0) for _ in range(6)],
            "chordtype_labels": [SimpleNamespace(color=0) for _ in range(6)],
            "key_rings": [SimpleNamespace(hidden=True) for _ in range(6)],
            "key_ring_until": [0] * 6,
            "time": time,
            "midi": midi,
            "NoteOn": type("NoteOn", (Message,), {}),
            "NoteOff": type("NoteOff", (Message,), {}),
        }
        exec(RUN_HANDLER, env)
        settings[0].update(note=62, channel=2)
        env["event"] = SimpleNamespace(key_number=0, pressed=False, released=True)
        exec(RUN_HANDLER, env)
        self.assertEqual(midi.sent, [("NoteOn", 61, 5), ("NoteOff", 61, 5)])
        self.assertIsNone(env["held_keys"][0])

    def test_drums_use_channel_ten(self):
        midi = Midi()
        settings = [{"note": 61, "velocity": 120, "channel": 0} for _ in range(6)]
        env = {
            "event": SimpleNamespace(key_number=0, pressed=True, released=False),
            "control_settings": {"keys": settings},
            "POT_C_INSTRUMENTS": True,
            "current_instrument": 0,
            "INSTRUMENTS": [("Drums", None)],
            "DRUM_NOTES": [36, 38, 42, 46, 49, 51],
            "DRUM_CHANNEL": 9,
            "MIDI_NOTE_NAMES": [str(i) for i in range(128)],
            "held_keys": [None] * 6,
            "active_notes": {},
            "chord_mode": False,
            "key_panels": [SimpleNamespace(fill=None) for _ in range(6)],
            "keynote_labels": [SimpleNamespace(color=0) for _ in range(6)],
            "chordtype_labels": [SimpleNamespace(color=0) for _ in range(6)],
            "key_rings": [SimpleNamespace(hidden=True) for _ in range(6)],
            "key_ring_until": [0] * 6,
            "time": time,
            "midi": midi,
            "NoteOn": type("NoteOn", (Message,), {}),
            "NoteOff": type("NoteOff", (Message,), {}),
        }
        exec(RUN_HANDLER, env)
        self.assertEqual(midi.sent, [("NoteOn", 36, 9)])

    def test_guitar_chord_release_survives_assignment_change(self):
        midi = Midi()
        settings = [{"note": 61, "velocity": 120, "channel": 2,
                     "chord_root": 0, "chord_shape": 0} for _ in range(6)]
        env = {
            "event": SimpleNamespace(key_number=0, pressed=True, released=False),
            "control_settings": {"keys": settings},
            "POT_C_INSTRUMENTS": False, "current_instrument": -1,
            "INSTRUMENTS": [], "DRUM_NOTES": [36, 38, 42, 46, 49, 51],
            "DRUM_CHANNEL": 9, "MIDI_NOTE_NAMES": [str(i) for i in range(128)],
            "held_keys": [None] * 6, "active_notes": {}, "chord_mode": True,
            "key_panels": [SimpleNamespace(fill=None) for _ in range(6)],
            "keynote_labels": [SimpleNamespace(color=0) for _ in range(6)],
            "chordtype_labels": [SimpleNamespace(color=0) for _ in range(6)],
            "key_rings": [SimpleNamespace(hidden=True) for _ in range(6)],
            "key_ring_until": [0] * 6, "time": time, "midi": midi,
            "NoteOn": type("NoteOn", (Message,), {}),
            "NoteOff": type("NoteOff", (Message,), {}),
        }
        exec(CHORD_HELPERS, env)
        exec(RUN_HANDLER, env)
        self.assertEqual([note for kind, note, _ in midi.sent if kind == "NoteOn"],
                         [48, 52, 55, 60, 64])  # open C: x32010
        settings[0].update(chord_root=7, chord_shape=1, channel=4)
        env["chord_mode"] = False
        env["event"] = SimpleNamespace(key_number=0, pressed=False, released=True)
        exec(RUN_HANDLER, env)
        self.assertEqual([note for kind, note, _ in midi.sent if kind == "NoteOff"],
                         [48, 52, 55, 60, 64])
        self.assertEqual(set(channel for _, _, channel in midi.sent), {2})

    def test_overlapping_chords_keep_shared_notes_held(self):
        midi = Midi()
        settings = [{"note": 61, "velocity": 120, "channel": 0,
                     "chord_root": 0, "chord_shape": 0} for _ in range(6)]
        env = {
            "event": SimpleNamespace(key_number=0, pressed=True, released=False),
            "control_settings": {"keys": settings},
            "POT_C_INSTRUMENTS": False, "current_instrument": -1,
            "INSTRUMENTS": [], "DRUM_NOTES": [36, 38, 42, 46, 49, 51],
            "DRUM_CHANNEL": 9, "MIDI_NOTE_NAMES": [str(i) for i in range(128)],
            "held_keys": [None] * 6, "active_notes": {}, "chord_mode": True,
            "key_panels": [SimpleNamespace(fill=None) for _ in range(6)],
            "keynote_labels": [SimpleNamespace(color=0) for _ in range(6)],
            "chordtype_labels": [SimpleNamespace(color=0) for _ in range(6)],
            "key_rings": [SimpleNamespace(hidden=True) for _ in range(6)],
            "key_ring_until": [0] * 6, "time": time, "midi": midi,
            "NoteOn": type("NoteOn", (Message,), {}),
            "NoteOff": type("NoteOff", (Message,), {}),
        }
        exec(CHORD_HELPERS, env)
        exec(RUN_HANDLER, env)
        env["event"] = SimpleNamespace(key_number=1, pressed=True, released=False)
        exec(RUN_HANDLER, env)
        self.assertEqual(len([message for message in midi.sent if message[0] == "NoteOn"]), 5)
        env["event"] = SimpleNamespace(key_number=0, pressed=False, released=True)
        exec(RUN_HANDLER, env)
        self.assertFalse(any(message[0] == "NoteOff" for message in midi.sent))
        env["event"] = SimpleNamespace(key_number=1, pressed=False, released=True)
        exec(RUN_HANDLER, env)
        self.assertEqual(len([message for message in midi.sent if message[0] == "NoteOff"]), 5)


if __name__ == "__main__":
    unittest.main()
