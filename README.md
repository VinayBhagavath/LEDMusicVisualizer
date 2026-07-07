# LED Matrix Music Visualizer

A 6-LED (2 row × 3 column) matrix driven by an Arduino Uno R3, reacting live
to an MP3 played from a laptop — no microphone involved. The laptop analyzes
the actual audio data as it plays and streams a volume level to the Arduino
over serial, which displays it as a bar graph across the matrix.

## Circuit Diagram

![Top-down LED circuit](Top-Down%20LED%20Circuit.JPG)

## Hardware

- Arduino Uno R3
- 74HC595 shift register (drives the 3 columns)
- 2× NPN transistor (2N2222 or similar, drives the 2 rows)
- 6× LED + 220Ω resistors (columns)
- 2× 1kΩ resistors (transistor bases)
- Breadboard + jumper wires

### Pinout

| Signal | Arduino Pin | Notes |
|---|---|---|
| 74HC595 RCLK (latch) | D11 | ST_CP / chip pin 12 |
| 74HC595 SRCLK (clock) | D12 | SH_CP / chip pin 11 |
| 74HC595 SER (data) | D10 | DS / chip pin 14 |
| Row 1 transistor base | D2 | via 1kΩ resistor |
| Row 2 transistor base | D3 | via 1kΩ resistor |

### Column wiring (confirmed via bit-scan test)

| Column | 74HC595 output |
|---|---|
| Column 1 | Q1 (bit 1) |
| Column 2 | Q2 (bit 2) |
| Column 3 | Q3 (bit 3) |

Q0 is unused — not a problem, just means that output pin isn't wired to anything.

## How it works

The display uses **multiplexing**: since the shift register can only hold one
column pattern at a time, each row is lit for a couple of milliseconds and
cycled fast enough (~250Hz) that persistence of vision makes both rows look
lit simultaneously. This logic lives in `refreshDisplay()` in the Arduino
sketch and doesn't change regardless of what's driving the pattern — hardcoded
test frames, or live audio, both just write into the same `grid[][]` array.

**Pipeline:**
1. `play_and_visualize.py` loads an MP3, plays it through your speakers, and
   in ~50ms chunks computes the volume (RMS) of the audio as it plays.
2. Each chunk's volume is scaled to a number 0–6 and sent over serial as a
   single byte, timed to match playback.
3. `music_visualizer.ino` reads that byte and lights that many LEDs as a
   left-to-right bar (both rows per column), using the existing multiplexed
   display loop.

## Files

- **`music_visualizer.ino`** — Arduino sketch. Upload this to the board.
- **`play_and_visualize.py`** — Laptop script. Plays the audio and sends
  levels over serial.

## Setup

### Arduino
1. Wire the board per the pinout table above.
2. Upload `music_visualizer.ino` via the Arduino IDE.
3. Close the Serial Monitor afterward — only one program can hold the
   serial port at a time, and the Python script needs it.

### Laptop
1. Install dependencies:
   ```bash
   pip install pydub numpy pyaudio pyserial
   ```
2. Install ffmpeg (required by pydub to decode MP3s):
   ```bash
   brew install ffmpeg        # macOS
   ```
   This can take 10–20+ minutes on a first install since it pulls in a long
   chain of codec dependencies — that's normal, not a hang. If a fresh
   terminal still can't find `ffmpeg`/`ffprobe` after install, run
   `source ~/.zshrc` (or your shell's config file) to refresh your PATH.
3. In `play_and_visualize.py`, set:
   - `MP3_PATH` to your audio file
   - `SERIAL_PORT` to your Arduino's port (find it via `ls /dev/tty.*` on
     macOS/Linux, or Device Manager on Windows, while the board is plugged in)
4. Run it:
   ```bash
   python play_and_visualize.py
   ```

## Testing history / verification steps

These were used to confirm the hardware before wiring up audio, and are
worth re-running if something stops working:

- **Individual LED test** — lights each of the 6 LEDs one at a time in
  sequence, confirming every row/column/transistor path is wired correctly.
- **Bit-scan test** — cycles through all 8 shift-register output bits with
  both rows held high, used to find which physical column each bit actually
  controls (this is how the Q1/Q2/Q3 mapping above was determined).
- **Hardcoded animation test** — a bouncing-dot pattern across both rows,
  used to confirm the multiplexed refresh loop runs without flicker.

## Tuning

- `CHUNK_MS` in the Python script controls responsiveness: smaller values
  react faster but look jumpier, larger values look smoother but laggier.
- The volume-to-level scaling uses the 95th percentile of the whole track's
  loudness (not the true max), so a few loud peaks don't make the rest of
  the song look artificially quiet by comparison.

## Possible next steps

- Split into frequency bands (bass/mid/treble) via FFT instead of a single
  overall volume level, if scaling to more LEDs/columns.
- Scale up to the original 8×6 (48-LED) matrix design — the multiplexing
  logic doesn't change conceptually, just its size.
- Add a physical enclosure and diffuser so individual LEDs blend into a
  smoother visual.