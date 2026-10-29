"""Run the key event handler without CircuitPython hardware: python -m unittest discover."""

import ast
from pathlib import Path
from types import SimpleNamespace
import time
import unittest


CODE = Path(__file__).parents[1] / "glyph_mini_2040_midi_keyset" / "code.py"
tree = ast.parse(CODE.read_text(encoding="utf-8"))
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
            "key_panels": [SimpleNamespace(fill=None) for _ in range(6)],
            "keynote_labels": [SimpleNamespace(color=0) for _ in range(6)],
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
            "key_panels": [SimpleNamespace(fill=None) for _ in range(6)],
            "keynote_labels": [SimpleNamespace(color=0) for _ in range(6)],
            "key_rings": [SimpleNamespace(hidden=True) for _ in range(6)],
            "key_ring_until": [0] * 6,
            "time": time,
            "midi": midi,
            "NoteOn": type("NoteOn", (Message,), {}),
            "NoteOff": type("NoteOff", (Message,), {}),
        }
        exec(RUN_HANDLER, env)
        self.assertEqual(midi.sent, [("NoteOn", 36, 9)])

    def test_chord_mode_sends_polyphonic_notes(self):
        midi = Midi()
        settings = [{"note": 61, "velocity": 120, "channel": 0, "chord_root": 4, "chord_shape": 0} for _ in range(6)]
        env = {
            "chord_mode": True,
            "guitar_chord": lambda r, s: (40, 47, 52),
            "chord_name": lambda r, s: "E",
            "active_notes": {},
            "chordtype_labels": [SimpleNamespace(color=0) for _ in range(6)],
            "event": SimpleNamespace(key_number=0, pressed=True, released=False),
            "control_settings": {"keys": settings},
            "POT_C_INSTRUMENTS": False,
            "current_instrument": -1,
            "INSTRUMENTS": [],
            "DRUM_NOTES": [36, 38, 42, 46, 49, 51],
            "DRUM_CHANNEL": 9,
            "MIDI_NOTE_NAMES": [str(i) for i in range(128)],
            "held_keys": [None] * 6,
            "key_panels": [SimpleNamespace(fill=None) for _ in range(6)],
            "keynote_labels": [SimpleNamespace(color=0) for _ in range(6)],
            "key_rings": [SimpleNamespace(hidden=True) for _ in range(6)],
            "key_ring_until": [0] * 6,
            "time": time,
            "midi": midi,
            "NoteOn": type("NoteOn", (Message,), {}),
            "NoteOff": type("NoteOff", (Message,), {}),
        }
        exec(RUN_HANDLER, env)
        self.assertEqual(midi.sent, [("NoteOn", 40, 0), ("NoteOn", 47, 0), ("NoteOn", 52, 0)])
        env["event"] = SimpleNamespace(key_number=0, pressed=False, released=True)
        exec(RUN_HANDLER, env)
        self.assertEqual(midi.sent, [
            ("NoteOn", 40, 0), ("NoteOn", 47, 0), ("NoteOn", 52, 0),
            ("NoteOff", 40, 0), ("NoteOff", 47, 0), ("NoteOff", 52, 0)
        ])
        self.assertIsNone(env["held_keys"][0])


if __name__ == "__main__":
    unittest.main()
