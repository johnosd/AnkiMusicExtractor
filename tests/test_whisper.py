"""
Smoke test for faster-whisper.
Usage: python test_whisper.py [audio_file]
"""
import sys

from faster_whisper import WhisperModel

model_size = "base"
audio_file = sys.argv[1] if len(sys.argv) > 1 else None

print(f"Loading faster-whisper model '{model_size}' on CPU (int8)...")
model = WhisperModel(model_size, device="cpu", compute_type="int8")
print("Model loaded OK.")

if audio_file:
    print(f"Transcribing: {audio_file}")
    segments, info = model.transcribe(audio_file, word_timestamps=True)
    print(f"Detected language: {info.language} (prob={info.language_probability:.2f})")
    for seg in segments:
        print(f"  [{seg.start:.2f}s -> {seg.end:.2f}s] {seg.text.strip()}")
else:
    print("No audio file provided. Pass a path as argument to transcribe.")
    print("Example: python test_whisper.py app/input/song.mp3")
