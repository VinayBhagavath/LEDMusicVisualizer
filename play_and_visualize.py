"""
Music visualizer — laptop side.

Loads an MP3, plays it through your speakers, and as it plays,
sends a single byte (0-6) over serial to the Arduino every ~50ms
representing how loud that instant of the song is. No microphone
involved at all — this reads the actual audio data directly.

Setup (run once):
    pip install pydub numpy pyaudio pyserial
    # pydub also needs ffmpeg installed and on your PATH:
    #   macOS:   brew install ffmpeg
    #   Windows: download from ffmpeg.org and add to PATH
    #   Linux:   sudo apt install ffmpeg

Before running:
    1. Set MP3_PATH below to your audio file.
    2. Set SERIAL_PORT below to your Arduino's port:
       - macOS/Linux: run `ls /dev/tty.*` (or /dev/cu.*) with Arduino
         plugged in, look for something like /dev/tty.usbmodem14101
       - Windows: check Device Manager > Ports (COM & LPT), e.g. "COM5"
       - Or check Arduino IDE > Tools > Port while it's plugged in.
    3. Make sure the Arduino IDE's Serial Monitor is CLOSED — only one
       program can hold the serial port at a time.
"""

import time
import numpy as np
from pydub import AudioSegment
import pyaudio
import serial

# ---- Config: edit these two for your setup ----
MP3_PATH = "/Users/jonleonard/Downloads/All Falls Down.mp3"
SERIAL_PORT = "/dev/tty.usbmodem101"  # change to your Arduino's port

BAUD_RATE = 9600
CHUNK_MS = 50       # size of each analysis/playback chunk, in milliseconds
NUM_LEVELS = 6      # matches your 6 LEDs


def load_audio(path):
    audio = AudioSegment.from_file(path)
    # Mono, standard sample rate/width — keeps the math simple and consistent
    audio = audio.set_channels(1).set_frame_rate(44100).set_sample_width(2)
    return audio


def rms_to_level(rms, max_rms):
    if max_rms == 0:
        return 0
    level = int((rms / max_rms) * NUM_LEVELS)
    return max(0, min(NUM_LEVELS, level))


def main():
    print("Loading audio...")
    audio = load_audio(MP3_PATH)
    samples = np.array(audio.get_array_of_samples(), dtype=np.int16)
    frame_rate = audio.frame_rate
    chunk_samples = int(frame_rate * (CHUNK_MS / 1000.0))

    print("Pre-analyzing volume levels for scaling...")
    rms_values = []
    for start in range(0, len(samples), chunk_samples):
        chunk = samples[start:start + chunk_samples]
        if len(chunk) == 0:
            continue
        rms = np.sqrt(np.mean(chunk.astype(np.float64) ** 2))
        rms_values.append(rms)
    # 95th percentile instead of true max, so a few loud peaks don't make
    # the rest of the song look artificially quiet by comparison
    max_rms = np.percentile(rms_values, 95)

    print(f"Connecting to Arduino on {SERIAL_PORT}...")
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE)
    time.sleep(2)  # Arduino resets when serial opens; give it time to boot

    p = pyaudio.PyAudio()
    stream = p.open(
        format=p.get_format_from_width(audio.sample_width),
        channels=1,
        rate=frame_rate,
        output=True,
    )

    print("Playing and sending levels... (Ctrl+C to stop)")
    raw_bytes = samples.tobytes()
    bytes_per_chunk = chunk_samples * 2  # 2 bytes per int16 sample

    try:
        for start in range(0, len(raw_bytes), bytes_per_chunk):
            chunk_bytes = raw_bytes[start:start + bytes_per_chunk]
            if len(chunk_bytes) == 0:
                break

            # Blocking write — takes roughly CHUNK_MS to return, which is
            # what keeps the level-sending in sync with actual playback
            stream.write(chunk_bytes)

            chunk_arr = np.frombuffer(chunk_bytes, dtype=np.int16)
            rms = np.sqrt(np.mean(chunk_arr.astype(np.float64) ** 2))
            level = rms_to_level(rms, max_rms)

            ser.write(bytes([level]))
    except KeyboardInterrupt:
        print("\nStopped early.")
    finally:
        # Turn all LEDs off on exit so it doesn't get stuck mid-pattern
        ser.write(bytes([0]))
        stream.stop_stream()
        stream.close()
        p.terminate()
        ser.close()
        print("Done.")


if __name__ == "__main__":
    main()