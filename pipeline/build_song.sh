#!/usr/bin/env bash
# One song: WAV -> stems (Demucs) -> chart.json + mix.mp3
# usage: pipeline/build_song.sh <song.wav> <slug> "<Title>"
#   e.g. pipeline/build_song.sh ~/Downloads/song.wav too-loud-to-die "Too Loud to Die"
# The WAV comes from Suno (MCP audio-download, format wav; uses one download credit).
set -euo pipefail
WAV="$1"; SLUG="$2"; TITLE="$3"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/work/$SLUG"; OUT="$ROOT/songs/$SLUG"
mkdir -p "$WORK" "$OUT"

cp "$WAV" "$WORK/song.wav"
# 4-stem model: separates bass much better than htdemucs_6s on dense rock mixes
python3 -m demucs -n htdemucs -o "$WORK/sep" "$WORK/song.wav"
python3 "$ROOT/pipeline/chart.py" "$WORK/sep/htdemucs/song" "$TITLE" "$OUT/chart.json"
ffmpeg -loglevel error -y -i "$WORK/song.wav" -ac 2 -b:a 160k "$OUT/mix.mp3"
echo "done: $OUT"
