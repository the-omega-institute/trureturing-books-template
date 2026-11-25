#!/usr/bin/env bash
# Concatenate the frames step's segments and mux the mixes into the requested videos (theme/film/plan.py), all
# with +faststart (moov first), so a browser starts playing before the download ends:
#   1080p (out/seg_*.mp4 → video_only.mp4, copied):    out/<outputs.narrated> (mix_voice.wav),
#                                                       out/<outputs.music_only> (mix_music.wav); AAC 192k
#   720p  (out/seg720_*.mp4 → video_720p.mp4, copied): out/<outputs.narrated_720p> (mix_voice.wav),
#                                                       out/<outputs.music_only_720p> (mix_music.wav); AAC 128k
# Audio is AAC at 48 kHz. Nothing is encoded again: the frames step encoded each size once. A film whose
# script.json opens chapters gets them as MP4 chapters (out/chapters.ffmeta, written by build.py --chapters).
# usage: theme/film/mux.sh <film dir>      Env: FILM_OUTPUTS (default: what film.json lists), FFMPEG.
# Adapted from trureturing-film films/*/mux.sh (Apache-2.0).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FILM="$(cd "$1" && pwd)"
OUT="$FILM/out"
FF="${FFMPEG:-ffmpeg}"
PYTHON="${PYTHON:-python3}"
PLAN="$("$PYTHON" "$HERE/plan.py" "$FILM")"
eval "$PLAN"
"$PYTHON" "$HERE/build.py" "$FILM" --chapters
cd "$OUT"
N="$(cat segments.txt 2>/dev/null || echo 0)"
[ "$N" -ge 1 ] || { echo "film: no out/segments.txt; run the frames step first" >&2; exit 1; }

# concat <segment prefix> <video>: the segments of every worker, stream-copied into one video
concat() {
  : > "$1.txt"
  for ((i = 0; i < N; i++)); do
    [ -f "$1_$i.mp4" ] || { echo "film: out/$1_$i.mp4 is missing; run the frames step (it encodes $RENDITIONS)" >&2; exit 1; }
    printf "file '%s_%d.mp4'\n" "$1" "$i" >> "$1.txt"
  done
  "$FF" -y -loglevel error -f concat -safe 0 -i "$1.txt" -c copy "$2"
}
# mux <video> <mix> <audio bit rate> <output>
mux() {
  [ -f "$2" ] || { echo "film: out/$2 is missing; run the mix step" >&2; exit 1; }
  local chap=()
  [ ! -f chapters.ffmeta ] || chap=(-i chapters.ffmeta -map_chapters 2)
  "$FF" -y -loglevel error -i "$1" -i "$2" ${chap[@]+"${chap[@]}"} -map 0:v -map 1:a -c:v copy -c:a aac -b:a "$3" \
    -ar 48000 -shortest -movflags +faststart "$4"
  WROTE+=("$4")
}
WROTE=()
case ",$RENDITIONS," in *,master,*)
  concat seg video_only.mp4
  [ -z "$NARRATED" ] || mux video_only.mp4 mix_voice.wav 192k "$NARRATED"
  [ -z "$MUSIC_ONLY" ] || mux video_only.mp4 mix_music.wav 192k "$MUSIC_ONLY" ;;
esac
case ",$RENDITIONS," in *,720p,*)
  concat seg720 video_720p.mp4
  [ -z "$NARRATED_720P" ] || mux video_720p.mp4 mix_voice.wav 128k "$NARRATED_720P"
  [ -z "$MUSIC_ONLY_720P" ] || mux video_720p.mp4 mix_music.wav 128k "$MUSIC_ONLY_720P" ;;
esac
[ ${#WROTE[@]} -gt 0 ] || { echo "film: no video requested ($OUTPUTS)" >&2; exit 1; }
ls -la "${WROTE[@]}"
echo MUX_OK
