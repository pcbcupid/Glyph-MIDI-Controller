# SPDX-FileCopyrightText: 2025 Liz Clark and Noe Ruiz for Adafruit Industries
#
# SPDX-License-Identifier: MIT
#
# Adapted for the PCB Cupid Glyph Mini 2040 (CircuitPython 10.x, Glyph Mini 2040 build):
#   - pins mapped to the Glyph Mini 2040 GPIO numbers (see PIN MAP below)
#   - SSD1306 or SH1106 128x64 OLED support
#   - Pot B sends pitch bend; pot readings are averaged and de-jittered
#   - runs without the OLED if none is connected (MIDI keys still work)
#   - potentiometers can be switched off until they are wired (floating ADC pins
#     would otherwise send random CC messages)
#
# PIN MAP (Glyph Mini 2040 GPIO -> part)
#   Keys 1-6        : GP2 GP3 GP4 GP5 GP6 GP7 (other leg of each switch to GND)
#   Encoder A / B   : GP8 / GP9   (encoder middle pin to GND)
#   Encoder button  : GP10          (other leg to GND)
#   Pots A / B / C  : wiper to GP26 / GP27 / GP28, outer legs to 3V3 and GND
#   OLED 128x64 I2C : SDA -> GP0, SCL -> GP1 (I2C0; GP8/GP9 are the encoder)

import board
import time
import busio
import simpleio
import displayio
import i2cdisplaybus
import rotaryio
import digitalio
import terminalio
import keypad
from digitalio import DigitalInOut, Direction
from adafruit_display_text import label
from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.roundrect import RoundRect
import adafruit_displayio_ssd1306
import adafruit_displayio_sh1106
import usb_midi
import adafruit_midi
from adafruit_midi.note_on          import NoteOn
from adafruit_midi.note_off         import NoteOff
from adafruit_midi.control_change import ControlChange
from adafruit_midi.pitch_bend import PitchBend
from adafruit_midi.program_change import ProgramChange
from analogio import AnalogIn
from adafruit_debouncer import Button

# midi note names
MIDI_NOTE_NAMES = [
        "C-2", "C#-2", "D-2", "D#-2", "E-2", "F-2", "F#-2", "G-2", "G#-2", "A-2", "A#-2", "B-2",
        "C-1", "C#-1", "D-1", "D#-1", "E-1", "F-1", "F#-1", "G-1", "G#-1", "A-1", "A#-1", "B-1",
        "C0", "C#0", "D0", "D#0", "E0", "F0", "F#0", "G0", "G#0", "A0", "A#0", "B0",
        "C1", "C#1", "D1", "D#1", "E1", "F1", "F#1", "G1", "G#1", "A1", "A#1", "B1",
        "C2", "C#2", "D2", "D#2", "E2", "F2", "F#2", "G2", "G#2", "A2", "A#2", "B2",
        "C3", "C#3", "D3", "D#3", "E3", "F3", "F#3", "G3", "G#3", "A3", "A#3", "B3",
        "C4", "C#4", "D4", "D#4", "E4", "F4", "F#4", "G4", "G#4", "A4", "A#4", "B4",
        "C5", "C#5", "D5", "D#5", "E5", "F5", "F#5", "G5", "G#5", "A5", "A#5", "B5",
        "C6", "C#6", "D6", "D#6", "E6", "F6", "F#6", "G6", "G#6", "A6", "A#6", "B6",
        "C7", "C#7", "D7", "D#7", "E7", "F7", "F#7", "G7", "G#7", "A7", "A#7", "B7",
        "C8", "C#8", "D8", "D#8", "E8", "F8", "F#8", "G8", "G#8", "A8", "A#8", "B8",
        "C9", "C#9", "D9", "D#9", "E9", "F9", "F#9", "G9", "G#9", "A9", "A#9", "B9"
        ]


# Set to True once the three potentiometers are wired to A2 / A1 / A0
POTS_CONNECTED = True    # pots on GP26/GP27/GP28, tested 0-3.3 V

# Pot B sends pitch bend (understood by synth apps without MIDI learn) instead of a CC.
# Centre of the pot = normal pitch. Set to False to make Pot B send its CC number again.
POT_B_PITCH_BEND = True

# Pot C selects the instrument: each position sends a MIDI Program Change
# (General MIDI numbers). "Drums" switches the keys to MIDI channel 10 and drum sounds.
POT_C_INSTRUMENTS = False   # True = Pot C picks instruments instead of sending its CC
INSTRUMENTS = [            # (name shown on OLED, GM program number or None for drums)
    ("Piano", 0), ("EPno", 4), ("Organ", 19), ("Guitr", 24), ("Bass", 33),
    ("Strng", 48), ("Choir", 52), ("Trmpt", 56), ("Sax", 65), ("Flute", 73),
    ("Lead", 80), ("Pad", 88), ("Drums", None),
]
DRUM_CHANNEL = 9           # MIDI channel 10 (0-based 9) is the GM drum channel
DRUM_NOTES = [36, 38, 42, 46, 49, 51]  # keys 1-6: kick, snare, closed/open hat, crash, ride
current_instrument = 0

# Guitar tuning, low E through high E. None means a muted string. The movable
# shapes are rooted on the low E string; shifting every fret preserves the
# exact guitar voicing, including doubled notes, in every key.
GUITAR_OPEN_STRINGS = (40, 45, 50, 55, 59, 64)
CHORD_ROOTS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
CHORD_SHAPES = (
    ("maj", (0, 2, 2, 1, 0, 0)),
    ("m", (0, 2, 2, 0, 0, 0)),
    ("5", (0, 2, 2, None, None, None)),
    ("sus2", (0, 2, 4, 4, None, 0)),
    ("sus4", (0, 2, 2, 2, 0, 0)),
    ("aug", (0, 3, 2, 1, 1, 0)),
    ("dim", (0, 1, 2, 0, None, None)),
    ("6", (0, 2, 2, 1, 2, 0)),
    ("m6", (0, 2, 2, 0, 2, 0)),
    ("7", (0, 2, 0, 1, 0, 0)),
    ("maj7", (0, 2, 1, 1, 0, 0)),
    ("m7", (0, 2, 0, 0, 0, 0)),
    ("mMaj7", (0, 2, 1, 0, 0, 0)),
    ("dim7", (0, 1, 2, 0, 2, None)),
    ("m7b5", (0, 1, 0, 0, None, None)),
    ("7sus4", (0, 2, 0, 2, 0, 0)),
    ("add9", (0, 2, 4, 1, 0, 0)),
    ("madd9", (0, 2, 4, 0, 0, 0)),
    ("9", (0, 2, 0, 1, 0, 2)),
    ("maj9", (0, 2, 1, 1, 0, 2)),
    ("m9", (0, 2, 0, 0, 0, 2)),
    ("13", (0, 2, 0, 1, 2, 2)),
    ("7b9", (0, 2, 0, 1, 0, 1)),
    ("7#9", (0, 2, 0, 1, 0, 3)),
    ("7b5", (0, 1, 0, 1, None, 0)),
    ("7#5", (0, 3, 0, 1, 1, 0)),
    ("6/9", (0, 2, 4, 1, 2, 2)),
)
# Familiar lower-fret fingerings; other combinations use movable shapes.
OPEN_CHORDS = {
    (0, "maj"): (None, 3, 2, 0, 1, 0),
    (1, "maj"): (None, 4, 3, 1, 2, 1),
    (2, "maj"): (None, None, 0, 2, 3, 2),
    (3, "maj"): (None, None, 1, 3, 4, 3),
    (4, "maj"): (0, 2, 2, 1, 0, 0),
    (5, "maj"): (1, 3, 3, 2, 1, 1),
    (7, "maj"): (3, 2, 0, 0, 0, 3),
    (9, "maj"): (None, 0, 2, 2, 2, 0),
    (11, "maj"): (None, 2, 4, 4, 4, 2),
    (0, "m"): (None, 3, 5, 5, 4, 3),
    (1, "m"): (None, 4, 6, 6, 5, 4),
    (2, "m"): (None, None, 0, 2, 3, 1),
    (4, "m"): (0, 2, 2, 0, 0, 0),
    (5, "m"): (1, 3, 3, 1, 1, 1),
    (7, "m"): (3, 5, 5, 3, 3, 3),
    (9, "m"): (None, 0, 2, 2, 1, 0),
    (0, "7"): (None, 3, 2, 3, 1, 0),
    (2, "7"): (None, None, 0, 2, 1, 2),
    (4, "7"): (0, 2, 0, 1, 0, 0),
    (7, "7"): (3, 2, 0, 0, 0, 1),
    (9, "7"): (None, 0, 2, 0, 2, 0),
    (1, "maj7"): (None, 4, 3, 1, 1, 1),
}

def guitar_chord(root, shape):
    """Return MIDI pitches in low-to-high string order for a guitar chord."""
    name, frets = CHORD_SHAPES[shape]
    frets = OPEN_CHORDS.get((root, name), frets)
    shift = 0 if (root, name) in OPEN_CHORDS else (root - 4) % 12
    return tuple(open_note + fret + shift for open_note, fret in zip(GUITAR_OPEN_STRINGS, frets)
                 if fret is not None)

def chord_name(root, shape):
    suffix = CHORD_SHAPES[shape][0]
    return CHORD_ROOTS[root] + ("" if suffix == "maj" else suffix)

# Set these two values to match the OLED fitted to your board.
# Common I2C addresses are 0x3C and 0x3D; see README if the screen is blank.
OLED_DRIVER = "SSD1306"  # "SH1106" or "SSD1306"
OLED_ADDRESS = 0x3C
OLED_SDA = board.GP0
OLED_SCL = board.GP1
OLED_CONTRAST = 0xFF     # brightness 0x01..0xFF - lower it if filled areas look striped

# Data structure to store all control settings
control_settings = {
    'pots': [
        {'cc_num': 1, 'range_min': 0, 'range_max': 127, 'channel': 0, 'current_val': 0},  # Pot A: modulation
        {'cc_num': 10, 'range_min': 0, 'range_max': 127, 'channel': 0, 'current_val': 0}, # Pot B: pitch bend (see POT_B_PITCH_BEND)
        {'cc_num': 11, 'range_min': 0, 'range_max': 127, 'channel': 0, 'current_val': 0}, # Pot C: expression
    ],
    'keys': [
        {'note': 61, 'velocity': 120, 'channel': 0, 'chord_root': 1, 'chord_shape': 1},  # C#m
        {'note': 64, 'velocity': 120, 'channel': 0, 'chord_root': 11, 'chord_shape': 0}, # B
        {'note': 66, 'velocity': 120, 'channel': 0, 'chord_root': 9, 'chord_shape': 0},  # A
        {'note': 68, 'velocity': 120, 'channel': 0, 'chord_root': 11, 'chord_shape': 0}, # B
        {'note': 73, 'velocity': 120, 'channel': 0, 'chord_root': 1, 'chord_shape': 1},  # C#m
        {'note': 75, 'velocity': 120, 'channel': 0, 'chord_root': 11, 'chord_shape': 0}, # B
    ]
}



#rotary encoder and button
encoder = rotaryio.IncrementalEncoder(board.GP8, board.GP9)
last_position = 0

#  midi setup
midi = adafruit_midi.MIDI(midi_out=usb_midi.ports[1], out_channel=0)

# Create keypad object with the pins (removed encoder button)
keys = keypad.Keys(
    pins=(board.GP2, board.GP3, board.GP4, board.GP5, board.GP6, board.GP7),
    value_when_pressed=False,  # Buttons pull to ground when pressed
    pull=True  # Enable internal pull-up resistors
)
held_keys = [None] * 6  # (pitches, channel) preserves the sound started by each press
active_notes = {}  # (channel, pitch) -> held key count, for overlapping chords
chord_mode = True  # Custom chord preset starts ready to play; long press switches modes

# Set up encoder button with debouncer
encoder_button_pin = DigitalInOut(board.GP10)
encoder_button_pin.direction = Direction.INPUT
encoder_button_pin.pull = digitalio.Pull.UP
encoder_button = Button(encoder_button_pin, value_when_pressed=False, long_duration_ms=500)

#  potentiometer setup
pot_A = AnalogIn(board.GP26)
pot_B = AnalogIn(board.GP27)
pot_C = AnalogIn(board.GP28)

#display setup
displayio.release_displays()

# oled (optional - without it the keys still send MIDI)
WIDTH = 128
HEIGHT = 64
oled_ready = False
try:
    i2c = busio.I2C(OLED_SCL, OLED_SDA)
    display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=OLED_ADDRESS)
    if OLED_DRIVER == "SH1106":
        # SH1106 RAM is 132 columns wide; 1.3" 128x64 panels show columns 2-129
        display = adafruit_displayio_sh1106.SH1106(display_bus, width=WIDTH, height=HEIGHT,
                                                   colstart=2)
        display.brightness = OLED_CONTRAST / 255  # driver's own contrast command
    else:
        display = adafruit_displayio_ssd1306.SSD1306(display_bus, width=WIDTH, height=HEIGHT)
    oled_ready = True
    print("OLED found:", OLED_DRIVER, hex(OLED_ADDRESS))
except (ValueError, RuntimeError, OSError, AttributeError) as e:
    print("No OLED at", hex(OLED_ADDRESS), "- running without display:", e)

    class _NoDisplay:  # stands in for the display so the menu code still runs
        root_group = None

    display = _NoDisplay()

if oled_ready:
    splash = displayio.Group()
    splash.append(label.Label(terminalio.FONT, text="GLYPH MIDI",
                              color=0xFFFFFF, x=34, y=16))
    notes = displayio.Group(x=15, y=27)
    notes.append(RoundRect(0, 13, 8, 6, 3, fill=0xFFFFFF))
    notes.append(Rect(6, 0, 2, 16, fill=0xFFFFFF))
    notes.append(RoundRect(15, 13, 8, 6, 3, fill=0xFFFFFF))
    notes.append(Rect(21, 0, 2, 16, fill=0xFFFFFF))
    notes.append(Rect(7, 0, 16, 3, fill=0xFFFFFF))
    splash.append(notes)
    display.root_group = splash
    for frame in range(20):
        notes.x = 15 + frame * 4
        notes.y = 27 + (frame % 4) // 2
        time.sleep(0.035)
    time.sleep(1.0)

# Home screen: three live knobs above six notes in physical order.
maingroup = displayio.Group()

rect_dict = [
    {'pos': (0, 2), 'dim': (42, 29)},
    {'pos': (42, 2), 'dim': (42, 29)},
    {'pos': (84, 2), 'dim': (44, 29)},
]
for key_index in range(6):
    rect_dict.append({'pos': (1 + key_index * 21, 34), 'dim': (21, 29)})

key_panels = []
key_rings = []
key_ring_until = [0] * 6
for index, box in enumerate(rect_dict):
    x, y = box['pos']
    w, h = box['dim']
    inset = 2 if index < 3 else 1
    panel = RoundRect(x + inset, y + 2, w - 2 * inset, h - 4,
                      3 if index < 3 else 6,
                      fill=0xFFFFFF if index < 3 else None,
                      outline=None if index < 3 else 0xFFFFFF)
    maingroup.append(panel)
    if index >= 3:
        key_panels.append(panel)
        ring = RoundRect(x, y, w, h, 7, fill=None, outline=0xFFFFFF)
        ring.hidden = True
        maingroup.append(ring)
        key_rings.append(ring)

for title, center in (("MOD", 21), ("BEND", 63), ("EXPR", 106)):
    heading = label.Label(terminalio.FONT, text=title, color=0x000000)
    heading.anchor_point = (0.5, 0)
    heading.anchored_position = (center, 7)
    maingroup.append(heading)

current_index = 0
selector_rects = []
for i, box in enumerate(rect_dict):
    bx, by = box['pos']
    bw, bh = box['dim']
    sr = RoundRect(bx, by, bw, bh, 6, fill=None, outline=0xFFFFFF)
    sr.hidden = (i != current_index)
    maingroup.append(sr)
    selector_rects.append(sr)

keynote_maingroup = displayio.Group()
keynotes = [
    {'num': control_settings['keys'][i]['note'],
     'pos': (12 + i * 21, 45)}
    for i in range(6)
]
keynote_labels = []
chordtype_labels = []
for key_index, keynote in enumerate(keynotes):
    key_settings = control_settings['keys'][key_index]
    note = label.Label(terminalio.FONT,
                       text=CHORD_ROOTS[key_settings['chord_root']] if chord_mode
                       else MIDI_NOTE_NAMES[keynote['num']],
                       color=0xFFFFFF)
    note.anchor_point = (0.5, 0)
    note.anchored_position = (keynote['pos'][0], 41) if chord_mode else keynote['pos']
    keynote_labels.append(note)
    keynote_maingroup.append(note)
    chord_type = label.Label(terminalio.FONT,
                             text=CHORD_SHAPES[key_settings['chord_shape']][0][:3]
                             if chord_mode else "", color=0xFFFFFF)
    chord_type.anchor_point = (0.5, 0)
    chord_type.anchored_position = (keynote['pos'][0], 52)
    chordtype_labels.append(chord_type)
    keynote_maingroup.append(chord_type)
maingroup.append(keynote_maingroup)

potval_maingroup = displayio.Group()
potvals_labels = []
for center in (21, 63, 106):
    value = label.Label(terminalio.FONT, text="0", color=0x000000)
    value.anchor_point = (0.5, 0)
    value.anchored_position = (center, 18)
    potvals_labels.append(value)
    potval_maingroup.append(value)
maingroup.append(potval_maingroup)

# Create edit page
editgroup = displayio.Group()

# Labels for Edit Page
header_area = label.Label(
    terminalio.FONT,
    text="",
    color=0x000000,
    x=0, y=10,
    background_color=0xFFFFFF,
    padding_left=34,
    padding_right=34,
    padding_top=2,
    padding_bottom=2,
    )
header_area.anchor_point = (0.5, 0.0)
header_area.anchored_position = (64, 2)

item1_area = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=4, y=25,)
item2_area = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=4, y=38,)
item3_area = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=4, y=52,)
item4_area = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=4, y=58,)

# Create separate labels for range min and max
range_label = label.Label(terminalio.FONT, text="Range:", color=0xFFFFFF, x=4, y=38,)
range_min_label = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=65, y=38,)
range_dash_label = label.Label(terminalio.FONT, text="-", color=0xFFFFFF, x=85, y=38,)
range_max_label = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=95, y=38,)

item_areas = [item1_area, item2_area, item3_area]
edit_rectangle = Rect(0, 0, 128, 14, fill=None, outline=0xFFFFFF)
range_rectangle = Rect(0, 0, 20, 14, fill=0x000000, outline=0xFFFFFF)

editgroup.append(edit_rectangle)
editgroup.append(header_area)
editgroup.append(item1_area)
editgroup.append(item2_area)
editgroup.append(item3_area)
editgroup.append(item4_area)
editgroup.append(range_rectangle)
range_rectangle.hidden = True

# Add the Group to the Display
display.root_group = maingroup
if oled_ready:
    del splash, notes

#  function to read analog input (average of 8 readings to calm ADC noise)
def val(pin):
    total = 0
    for _ in range(8):
        total += pin.value
    return total // 8

POT_DEADBAND = 2   # a knob must move more than this many steps before a message is sent

def snap(v, pot):
    # values within 2 steps of either end become exactly the end value, so a knob
    # parked at its end stays silent instead of flickering between neighbours
    lo, hi = control_settings['pots'][pot]['range_min'], control_settings['pots'][pot]['range_max']
    if abs(v - lo) <= 2:
        return lo
    if abs(v - hi) <= 2:
        return hi
    return v

# Function to update edit mode display
def update_edit_display(index):
    global item_areas
    # First, remove the range components if they exist in editgroup
    if range_label in editgroup:
        editgroup.remove(range_label)
        editgroup.remove(range_min_label)
        editgroup.remove(range_dash_label)
        editgroup.remove(range_max_label)
    if index < 3:  # Potentiometer
        item_areas = [item1_area, item2_area, item3_area]
        item1_area.y, item2_area.y, item3_area.y = 25, 38, 52
        item4_area.text = ""
        p = control_settings['pots'][index]
        header_area.text = f"EDIT POT {'ABC'[index]}"
        item1_area.text = f"CC Number:     {p['cc_num']}"
        # Clear item2_area text since we'll use separate labels
        item2_area.text = ""
        # Add range components
        editgroup.append(range_label)
        editgroup.append(range_min_label)
        editgroup.append(range_dash_label)
        editgroup.append(range_max_label)
        range_min_label.text = str(p['range_min'])
        range_max_label.text = str(p['range_max'])
        item3_area.text = f"MIDI Channel:  {p['channel'] + 1}"
    elif chord_mode:  # Guitar chord button
        item_areas = [item1_area, item2_area, item3_area, item4_area]
        item1_area.y, item2_area.y, item3_area.y, item4_area.y = 21, 33, 45, 57
        k = index - 3
        s = control_settings['keys'][k]
        header_area.text = f"CHORD KEY {k + 1}"
        item1_area.text = f"Root: {CHORD_ROOTS[s['chord_root']]}"
        item2_area.text = f"Shape: {CHORD_SHAPES[s['chord_shape']][0]}"
        item3_area.text = f"Velocity: {s['velocity']}"
        item4_area.text = f"Channel: {s['channel'] + 1}"
    else:  # Single note button
        item_areas = [item1_area, item2_area, item3_area]
        item1_area.y, item2_area.y, item3_area.y = 25, 38, 52
        item4_area.text = ""
        k = index - 3
        s = control_settings['keys'][k]
        note_name = MIDI_NOTE_NAMES[s['note']]
        header_area.text = f"EDIT KEY {k + 1}"
        item1_area.text = f"MIDI Note:     {note_name}"
        item2_area.text = f"Velocity:      {s['velocity']}"
        item3_area.text = f"MIDI Channel:  {s['channel'] + 1}"

#  variables for last read value
pot_A_val2 = 0
pot_B_val2 = 0
pot_C_val2 = 0

edit_mode = False
edit_current_index = 0
edit_active = False  # Whether we're actively editing a value
range_edit_selection = 0  # 0 for min, 1 for max
range_edit_active = False  # New variable to track if we're actively editing a range value

while True:
    # Update encoder button state
    encoder_button.update()

    # Handle encoder button presses
    if encoder_button.short_count == 2:
        # send midi panic
        for channel in range(16):
            midi.send(ControlChange(123, 0), channel=channel)
        active_notes.clear()
        held_keys = [None] * 6

    elif encoder_button.short_count == 1 and not encoder_button.long_press:
        if not edit_mode:
            # Short press enters edit mode
            update_edit_display(current_index)
            edit_current_index = 0
            edit_rectangle.x = 0
            edit_rectangle.y = item_areas[edit_current_index].y - 7
            edit_rectangle.fill = None
            edit_active = False
            range_rectangle.hidden = True
            display.root_group = editgroup
            edit_mode = True
        elif current_index < 3 and edit_current_index == 1:
            # Range editing on Potentiometers
            if not edit_active:
                edit_active = True
                range_edit_selection = 0
                range_rectangle.hidden = False
                range_rectangle.x = range_min_label.x - 2
                range_rectangle.y = range_min_label.y - 7
                range_rectangle.fill = 0xFFFFFF
                range_min_label.color = 0x000000
                range_max_label.color = 0xFFFFFF
            elif range_edit_selection == 0:
                # Switch to editing Max
                range_edit_selection = 1
                range_rectangle.x = range_max_label.x - 2
                range_rectangle.y = range_max_label.y - 7
                range_min_label.color = 0xFFFFFF
                range_max_label.color = 0x000000
            else:
                # Confirm range and return to line navigation
                edit_active = False
                range_rectangle.hidden = True
                range_min_label.color = 0xFFFFFF
                range_max_label.color = 0xFFFFFF
        else:
            # Standard parameters: toggle editing state
            edit_active = not edit_active
            if edit_active:
                edit_rectangle.fill = 0xFFFFFF
                item_areas[edit_current_index].color = 0x000000
            else:
                edit_rectangle.fill = None
                item_areas[edit_current_index].color = 0xFFFFFF

    # Long press handling
    if encoder_button.long_press:
        if not edit_mode:
            # Long press on home page switches between notes and guitar chords
            chord_mode = not chord_mode
            for key_index, key_label in enumerate(keynote_labels):
                settings = control_settings['keys'][key_index]
                if chord_mode:
                    key_label.text = CHORD_ROOTS[settings['chord_root']]
                    key_label.anchored_position = (12 + key_index * 21, 41)
                    chordtype_labels[key_index].text = CHORD_SHAPES[settings['chord_shape']][0][:3]
                else:
                    key_label.text = MIDI_NOTE_NAMES[settings['note']]
                    key_label.anchored_position = (12 + key_index * 21, 45)
                    chordtype_labels[key_index].text = ""
            print("Mode:", "guitar chords" if chord_mode else "single notes")
        else:
            # Long press in edit mode exits back to main screen
            display.root_group = maingroup
            edit_mode = False
            edit_active = False
            range_edit_active = False
            edit_rectangle.fill = None
            item_areas[edit_current_index].color = 0xFFFFFF
            if current_index < 3:
                range_min_label.color = 0xFFFFFF
                range_max_label.color = 0xFFFFFF
                range_label.color = 0xFFFFFF
                range_dash_label.color = 0xFFFFFF
                range_rectangle.hidden = True

    event = keys.events.get()

    if event:
        # event.key_number gives you the index (0-5) of which button
        key_index = event.key_number

        in_chord_mode = globals().get('chord_mode', False)
        drums = (not in_chord_mode and POT_C_INSTRUMENTS and current_instrument >= 0
                 and INSTRUMENTS[current_instrument][1] is None)
        key_settings = control_settings['keys'][key_index]
        key_note = DRUM_NOTES[key_index] if drums else key_settings['note']
        key_channel = DRUM_CHANNEL if drums else key_settings['channel']

        if event.pressed:
            pitches = (guitar_chord(key_settings['chord_root'], key_settings['chord_shape'])
                       if in_chord_mode else (key_note,))
            held_keys[key_index] = (pitches, key_channel)
            notes_dict = globals().get('active_notes', None)
            for pitch in pitches:
                note_id = (key_channel, pitch)
                if notes_dict is not None:
                    if not notes_dict.get(note_id, 0):
                        midi.send(NoteOn(pitch, key_settings['velocity']), channel=key_channel)
                    notes_dict[note_id] = notes_dict.get(note_id, 0) + 1
                else:
                    midi.send(NoteOn(pitch, key_settings['velocity']), channel=key_channel)
            key_panels[key_index].fill = 0xFFFFFF
            keynote_labels[key_index].color = 0x000000
            if "chordtype_labels" in globals():
                chordtype_labels[key_index].color = 0x000000
            key_rings[key_index].hidden = False
            key_ring_until[key_index] = time.monotonic() + 0.12
            print("Key", key_index + 1, "pressed ->",
                  chord_name(key_settings['chord_root'], key_settings['chord_shape'])
                  if in_chord_mode else MIDI_NOTE_NAMES[key_note])

        if event.released:
            # Release exactly the pitches and channel used at press time, even
            # if the mode or assignment changed while the key was held.
            if held_keys[key_index] is not None:
                pitches, off_channel = held_keys[key_index]
                notes_dict = globals().get('active_notes', None)
                for pitch in pitches:
                    note_id = (off_channel, pitch)
                    if notes_dict is not None:
                        count = notes_dict.get(note_id, 0)
                        if count <= 1:
                            notes_dict.pop(note_id, None)
                            midi.send(NoteOff(pitch, key_settings['velocity']), channel=off_channel)
                        else:
                            notes_dict[note_id] = count - 1
                    else:
                        midi.send(NoteOff(pitch, key_settings['velocity']), channel=off_channel)
            held_keys[key_index] = None
            key_panels[key_index].fill = None
            keynote_labels[key_index].color = 0xFFFFFF
            if "chordtype_labels" in globals():
                chordtype_labels[key_index].color = 0xFFFFFF

    now = time.monotonic()
    for key_index, until in enumerate(key_ring_until):
        if until and now >= until:
            key_rings[key_index].hidden = True
            key_ring_until[key_index] = 0

    position = encoder.position

    # Check if encoder moved
    if position != last_position:
        if not edit_mode:
            # Main menu navigation
            old_index = current_index
            if position > last_position:
                current_index = (current_index + 1) % len(rect_dict)
            else:
                current_index = (current_index - 1) % len(rect_dict)

            selector_rects[old_index].hidden = True
            selector_rects[current_index].hidden = False
            last_position = position

        elif edit_mode and not edit_active:
            # Edit mode navigation - cycle through editable items
            # First restore previous item colors
            item_areas[edit_current_index].color = 0xFFFFFF

            if position > last_position:
                edit_current_index = (edit_current_index + 1) % len(item_areas)
            else:
                edit_current_index = (edit_current_index - 1) % len(item_areas)

            # Update rectangle position to highlight current item
            edit_rectangle.x = 0
            edit_rectangle.y = item_areas[edit_current_index].y - 7
            last_position = position

        elif edit_mode and edit_active:
            # Actively editing a value
            direction = 1 if position > last_position else -1

            if current_index < 3:  # Editing potentiometer
                pot_settings = control_settings['pots'][current_index]

                if edit_current_index == 0:  # CC Number
                    pot_settings['cc_num'] = (pot_settings['cc_num'] + direction) % 128
                    item1_area.text = f"CC Number:     {pot_settings['cc_num']}"
                elif edit_current_index == 1:  # Range editing
                    if range_edit_selection == 0:  # Editing min
                        pot_settings['range_min'] = (pot_settings['range_min'] + direction) % 128
                        range_min_label.text = f"{pot_settings['range_min']}"
                    else:  # Editing max
                        pot_settings['range_max'] = (pot_settings['range_max'] + direction) % 128
                        range_max_label.text = f"{pot_settings['range_max']}"
                elif edit_current_index == 2:  # MIDI Channel
                    pot_settings['channel'] = (pot_settings['channel'] + direction) % 16
                    item3_area.text = f"MIDI Channel:  {pot_settings['channel'] + 1}"

            elif chord_mode:  # Editing guitar chord key
                key_index = current_index - 3
                key_settings = control_settings['keys'][key_index]
                if edit_current_index == 0:
                    key_settings['chord_root'] = (key_settings['chord_root'] + direction) % 12
                    item1_area.text = f"Root: {CHORD_ROOTS[key_settings['chord_root']]}"
                elif edit_current_index == 1:
                    key_settings['chord_shape'] = (key_settings['chord_shape'] + direction) % len(CHORD_SHAPES)
                    item2_area.text = f"Shape: {CHORD_SHAPES[key_settings['chord_shape']][0]}"
                elif edit_current_index == 2:
                    key_settings['velocity'] = max(1, min(127, key_settings['velocity'] + direction))
                    item3_area.text = f"Velocity: {key_settings['velocity']}"
                else:
                    key_settings['channel'] = (key_settings['channel'] + direction) % 16
                    item4_area.text = f"Channel: {key_settings['channel'] + 1}"
                keynote_labels[key_index].text = CHORD_ROOTS[key_settings['chord_root']]
                chordtype_labels[key_index].text = CHORD_SHAPES[key_settings['chord_shape']][0][:3]
            else:  # Editing single-note key
                key_index = current_index - 3
                key_settings = control_settings['keys'][key_index]

                if edit_current_index == 0:  # MIDI Note
                    key_settings['note'] = (key_settings['note'] + direction) % len(MIDI_NOTE_NAMES)
                    key_note_name = MIDI_NOTE_NAMES[key_settings['note']]
                    item1_area.text = f"MIDI Note:     {key_note_name}"
                    # Update the main screen label too
                    keynote_labels[key_index].text = key_note_name
                elif edit_current_index == 1:  # Velocity
                    key_settings['velocity'] = max(1, min(127, key_settings['velocity'] + direction))
                    item2_area.text = f"Velocity:      {key_settings['velocity']}"
                elif edit_current_index == 2:  # MIDI Channel
                    key_settings['channel'] = (key_settings['channel'] + direction) % 16
                    item3_area.text = f"MIDI Channel:  {key_settings['channel'] + 1}"

            last_position = position

    if not POTS_CONNECTED:
        continue

    pot_A_val1 = round(simpleio.map_range(val(pot_A), 0, 65535,
                                          control_settings['pots'][0]['range_min'],
                                          control_settings['pots'][0]['range_max']))
    pot_B_val1 = round(simpleio.map_range(val(pot_B), 0, 65535,
                                          control_settings['pots'][1]['range_min'],
                                          control_settings['pots'][1]['range_max']))
    pot_C_val1 = round(simpleio.map_range(val(pot_C), 0, 65535,
                                          control_settings['pots'][2]['range_min'],
                                          control_settings['pots'][2]['range_max']))

    #  if modulation value is updated...
    pot_A_val1 = snap(pot_A_val1, 0)
    p0 = control_settings['pots'][0]
    if abs(pot_A_val1 - pot_A_val2) > POT_DEADBAND or \
            (pot_A_val1 != pot_A_val2 and pot_A_val1 in (p0['range_min'], p0['range_max'])):
        #  update pot_A_val2
        pot_A_val2 = pot_A_val1
        #  create integer
        modulation = int(pot_A_val2)
        p0['current_val'] = modulation
        potvals_labels[0].text = str(modulation)
        #  create CC message
        modWheel = ControlChange(p0['cc_num'], modulation)
        #  send CC message
        midi.send(modWheel, channel=p0['channel'])

    pot_B_val1 = snap(pot_B_val1, 1)
    p1 = control_settings['pots'][1]
    if abs(pot_B_val1 - pot_B_val2) > POT_DEADBAND or \
            (pot_B_val1 != pot_B_val2 and pot_B_val1 in (p1['range_min'], p1['range_max'])):
        #  update pot_B_val2
        pot_B_val2 = pot_B_val1
        #  create integer
        ControllerB = int(pot_B_val2)
        p1['current_val'] = ControllerB
        potvals_labels[1].text = str(ControllerB)
        #  create CC message
        if POT_B_PITCH_BEND:
            # 0..127 -> 0..16383; middle of the pot (62..65) = 8192 = exactly no bend
            if 62 <= ControllerB <= 65:
                bend = 8192
            else:
                bend = min(16383, ControllerB * 129)
            midi.send(PitchBend(bend), channel=p1['channel'])
        else:
            ControlB = ControlChange(p1['cc_num'], ControllerB)
            #  send CC message
            midi.send(ControlB, channel=p1['channel'])

    pot_C_val1 = snap(pot_C_val1, 2)
    p2 = control_settings['pots'][2]
    if abs(pot_C_val1 - pot_C_val2) > POT_DEADBAND or \
            (pot_C_val1 != pot_C_val2 and pot_C_val1 in (p2['range_min'], p2['range_max'])):
        #  update pot_c_val2
        pot_C_val2 = pot_C_val1
        #  create integer
        ControllerC = int(pot_C_val2)
        p2['current_val'] = ControllerC
        potvals_labels[2].text = str(ControllerC)
        #  create CC message
        if POT_C_INSTRUMENTS:
            # split the pot into one zone per instrument; only switch once the pot is
            # 2 steps inside the new zone, so noise at a zone border can't flip back and forth
            count = len(INSTRUMENTS)
            index = min(count - 1, ControllerC * count // 128)
            zone_low = index * 128 / count
            zone_high = (index + 1) * 128 / count
            inside = (index == 0 or ControllerC >= zone_low + 2) and \
                     (index == count - 1 or ControllerC <= zone_high - 2)
            if index != current_instrument and (current_instrument < 0 or inside):
                midi.send(ControlChange(123, 0))  # all notes off on the old channel
                name, program = INSTRUMENTS[index]
                if program is None:
                    midi.out_channel = DRUM_CHANNEL
                else:
                    midi.out_channel = p2['channel']
                    midi.send(ProgramChange(program))
                current_instrument = index
                print("Instrument:", name)
            if current_instrument >= 0:
                potvals_labels[2].text = INSTRUMENTS[current_instrument][0]
        else:
            ControlC = ControlChange(p2['cc_num'], ControllerC)
            #  send CC message
            midi.send(ControlC, channel=p2['channel'])

    time.sleep(0.002)
