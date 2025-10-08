#!/usr/bin/env python3
"""Test script to verify sound duration detection from WAV files."""

import os
import wave

# Sound file paths
User = os.popen('echo ${SUDO_USER:-$LOGNAME}').readline().strip()
UserHome = os.popen('getent passwd %s | cut -d: -f 6' % User).readline().strip()
SOUND_DIR = f"{UserHome}/pidog/sounds/"
LOCAL_SOUND_DIR = "audio/"


def get_sound_duration(sound_name: str) -> float:
    """Get the duration of a WAV sound file by reading its header.
    
    Args:
        sound_name: Name of the sound file (without extension)
        
    Returns:
        Duration in seconds, or 0.0 if file not found or error reading
    """
    # Try both local and system sound directories
    possible_paths = [
        os.path.join(LOCAL_SOUND_DIR, f"{sound_name}.wav"),
        os.path.join(SOUND_DIR, f"{sound_name}.wav"),
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            try:
                with wave.open(path, 'r') as wav_file:
                    frames = wav_file.getnframes()
                    rate = wav_file.getframerate()
                    duration = frames / float(rate)
                    
                    # Show detailed info
                    channels = wav_file.getnchannels()
                    sampwidth = wav_file.getsampwidth()
                    
                    print(f"\n✅ {sound_name}")
                    print(f"   Path: {path}")
                    print(f"   Duration: {duration:.3f} seconds")
                    print(f"   Sample Rate: {rate} Hz")
                    print(f"   Channels: {channels}")
                    print(f"   Sample Width: {sampwidth} bytes")
                    print(f"   Total Frames: {frames:,}")
                    
                    return duration
            except Exception as e:
                print(f"\n❌ {sound_name}")
                print(f"   Error reading {path}: {e}")
                continue
    
    print(f"\n⚠️  {sound_name}")
    print(f"   Sound file not found in:")
    for path in possible_paths:
        print(f"   - {path}")
    return 0.0


def main():
    """Test sound duration detection for all sound-playing actions."""
    print("=" * 70)
    print("SOUND DURATION DETECTION TEST")
    print("=" * 70)
    
    sound_files = [
        ("bark", "single_bark_1"),
        ("bark_harder", "single_bark_2"),
        ("pant", "pant"),
        ("howling", "howling"),
    ]
    
    total_duration = 0.0
    detected_count = 0
    
    for action_name, sound_file in sound_files:
        duration = get_sound_duration(sound_file)
        if duration > 0:
            total_duration += duration
            detected_count += 1
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"✅ Detected: {detected_count}/{len(sound_files)} sound files")
    print(f"⏱️  Total Duration: {total_duration:.3f} seconds")
    
    if detected_count == len(sound_files):
        print("\n🎉 All sound files detected successfully!")
        print("   The action manager will use these precise durations.")
    else:
        print(f"\n⚠️  Warning: {len(sound_files) - detected_count} sound file(s) missing")
        print("   Check the paths above and ensure WAV files exist.")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
