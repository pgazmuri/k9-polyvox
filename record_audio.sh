#!/bin/bash


# Or fallback to defaults (less accurate but works broadly)
DEFAULT_SOURCE=$(pactl info | grep "Default Source" | awk -F': ' '{print $2}' | head -n 1)
DEFAULT_SINK=$(pactl info | grep "Default Sink" | awk -F': ' '{print $2}' | head -n 1)

# Derive monitor name for sink
MONITOR_NAME="${DEFAULT_SINK}.monitor"

echo "Default source: $DEFAULT_SOURCE"
echo "Default sink: $DEFAULT_SINK"
echo "Monitor device: $MONITOR_NAME"

# Record with ffmpeg
ffmpeg -f pulse -i "$MONITOR_NAME" -f pulse -i "$DEFAULT_SOURCE" \
  -filter_complex amix=inputs=2:duration=longest -ac 2 -ar 48000 -t 00:01:00 mixed_output2.wav
