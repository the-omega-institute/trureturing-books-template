#!/usr/bin/env bash
# The film pipeline, one entry point for every film directory (books/<slug>/films/<name>).
#
#   theme/film/film.sh <film dir> <step> [args…]
#   theme/film/film.sh setup                       (= theme/film/setup.sh, once per machine)
#
# ./tbook build films|site|all runs `all <the keys of film.json outputs>` (FILM_STRICT=1) for each film whose
# build inputs changed (the others are restored from the build cache) and copies those videos to
# build/films/<slug>/<id>/; the steps below are for working on a film by hand.
#
# Outputs (film.json "outputs"): narrated_720p (the players' video) and cover always; narrated (1080p),
# music_only (1080p) and music_only_720p only when listed. The steps make the requested outputs: the
# arguments of `all`, else $FILM_OUTPUTS (keys separated by spaces or commas), else what film.json lists
# (theme/film/plan.py). The frames are always drawn at 1920x1080; a 1080p master is encoded only for a
# 1080p video, the 720p videos are scaled from the frames in the same pass.
# steps (all outputs go to <film dir>/out/, which is git-ignored):
#   setup      the film venv and its pinned packages, the Kokoro model (.cache/film), fonts   → setup.sh
#   tts        narration line by line with Kokoro-82M → out/tts/, out/narration.wav, out/timeline.json
#   timeline   provisional timing from script.json (no TTS) → out/timeline.provisional.json
#   build      out/index.html (engine + scenes + data + fonts + timeline)
#   music      procedural score and SFX synced to the timeline → out/music_bed.wav
#   mix        ducked narration mix → out/mix_voice.wav; the music-only mix out/mix_music.wav only for a
#              music-only video
#   frames     every frame through headless Chromium (parallel workers), encoded once per size:
#              out/seg720_<i>.mp4 (1280x720, CRF 19) for a 720p video, out/seg_<i>.mp4 (1080p, CRF 17) for a
#              1080p video
#   cover      out/<outputs.cover> (1920x1080)
#   render     frames + cover
#   mux        the requested videos from the segments and the mixes (no re-encode; AAC 48 kHz, faststart):
#              out/<outputs.narrated_720p>, out/<outputs.music_only_720p>, out/<outputs.narrated>,
#              out/<outputs.music_only>
#   poster     out/<outputs.cover> and the committed <film dir>/poster.jpg (≤ 300 KB): run it by hand and
#              commit the poster; the build never writes it
#   clip       a short silent preview: clip [start s] [seconds] [WxH] → out/clip.mp4
#   shot       stills for review: shot <t1> <t2> … [--size WxH] [--poster] → out/shots/
#   serve      preview at http://127.0.0.1:<port>/index.html?play (or ?t=12.5, ?poster)
#   player     narrated MP3 audio plus the timed canvas scene, fonts and optional 3D assets for Pages
#   all        all [<output key> …]: tts, music, mix, frames, mux, cover for the requested outputs (default:
#              what film.json lists, i.e. what the build publishes; run setup first)
#
# Environment: PYTHON (default: $FILM_CACHE/venv/bin/python when setup.sh made it, else python3), FILM_CACHE
# (default .cache/film), PW_CHROMIUM_PATH (Chromium for Playwright), FFMPEG (default: ffmpeg on PATH),
# FILM_OUTPUTS, FILM_WORKERS, FILM_STRICT=1 (fail instead of using provisional timing or system fonts),
# KOKORO_MODEL_DIR.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

# the comment block above, without its first line
usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; exit 2; }
if [ "${1:-}" = "setup" ] && [ $# -eq 1 ]; then exec "$HERE/setup.sh"; fi
[ $# -ge 2 ] || usage
FILM="$(cd "$1" 2>/dev/null && pwd)" || { echo "film: no such directory: $1" >&2; exit 2; }
STEP="$2"; shift 2
[ -f "$FILM/film.json" ] || { echo "film: $FILM has no film.json" >&2; exit 2; }
OUT="$FILM/out"
mkdir -p "$OUT"

# The same choice as tools/tbook/film.py film_python().
if [ -z "${PYTHON:-}" ]; then
  VENV_PY="${FILM_CACHE:-$ROOT/.cache/film}/venv/bin/python"
  if [ -x "$VENV_PY" ]; then PYTHON="$VENV_PY"; else PYTHON=python3; fi
fi
export PYTHON
py() { "$PYTHON" "$HERE/$1" "${@:2}"; }
meta() { "$PYTHON" -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d.get("outputs",{}).get(sys.argv[2],""))' "$FILM/film.json" "$1"; }
ffmpeg_bin() {
  if [ -n "${FFMPEG:-}" ]; then echo "$FFMPEG"; return; fi
  if command -v ffmpeg >/dev/null 2>&1; then command -v ffmpeg; return; fi
  echo "film: ffmpeg not found (install it, e.g. apt-get install ffmpeg, or set FFMPEG)" >&2; exit 1
}
cover() { py build.py "$FILM" && node "$HERE/poster.js" "$OUT" "$(meta cover)"; }

case "$STEP" in
  setup)    "$HERE/setup.sh" ;;
  tts)      py tts.py "$FILM" "$@" ;;
  timeline) py build.py "$FILM" --timeline-only ;;
  build)    py build.py "$FILM" "$@" ;;
  music)    py music.py "$FILM" "$@" ;;
  mix)      py mix.py "$FILM" "$@" ;;
  frames)   FFMPEG="$(ffmpeg_bin)" "$HERE/render_all.sh" "$FILM" ;;
  cover)    cover ;;
  render)   FFMPEG="$(ffmpeg_bin)" "$HERE/render_all.sh" "$FILM" && cover ;;
  mux)      FFMPEG="$(ffmpeg_bin)" "$HERE/mux.sh" "$FILM" ;;
  poster)   py build.py "$FILM" && node "$HERE/poster.js" "$OUT" "$(meta cover)" "$FILM/poster.jpg" ;;
  clip)
    START="${1:-0}"; SECS="${2:-3}"; SIZE="${3:-960x540}"
    py build.py "$FILM"
    END="$("$PYTHON" -c 'import sys;print(float(sys.argv[1])+float(sys.argv[2]))' "$START" "$SECS")"
    FFMPEG="$(ffmpeg_bin)" node "$HERE/render.js" "$OUT" --start "$START" --end "$END" --size "$SIZE" --crf 23 --preset veryfast --output clip.mp4 ;;
  shot)     py build.py "$FILM" && node "$HERE/shot.js" "$OUT" "$@" ;;
  serve)
    py build.py "$FILM"
    PORT="${PORT:-$("$PYTHON" -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')}"
    echo "film: http://127.0.0.1:$PORT/index.html?play  (?t=12.5 for one frame, ?poster for the poster)"
    exec "$PYTHON" -m http.server "$PORT" --bind 127.0.0.1 --directory "$OUT" ;;
  player)
    export FILM_OUTPUTS=narrated_720p FILM_STRICT=1
    py tts.py "$FILM"
    py music.py "$FILM"
    py mix.py "$FILM"
    DURATION="$("$PYTHON" -c 'import json,sys;print(json.load(open(sys.argv[1]))["duration"])' "$OUT/timeline.json")"
    "$(ffmpeg_bin)" -hide_banner -loglevel error -y -i "$OUT/mix_voice.wav" -t "$DURATION" -vn -c:a libmp3lame -b:a 160k "$OUT/audio.mp3"
    py build.py "$FILM" --player ;;
  all)
    # the requested outputs: the arguments, else $FILM_OUTPUTS, else film.json's (plan.py checks the keys)
    if [ $# -gt 0 ]; then export FILM_OUTPUTS="$*"; else export FILM_OUTPUTS="${FILM_OUTPUTS:-}"; fi
    PLAN="$(py plan.py "$FILM")"
    eval "$PLAN"
    echo "film: making $OUTPUTS (frames encoded as ${RENDITIONS:-nothing})"
    FF="$(ffmpeg_bin)"
    py tts.py "$FILM"
    py music.py "$FILM"
    py mix.py "$FILM"
    if [ -n "$RENDITIONS" ]; then
      FILM_STRICT=1 FFMPEG="$FF" "$HERE/render_all.sh" "$FILM"
      FFMPEG="$FF" "$HERE/mux.sh" "$FILM"
    fi
    if [ -n "$COVER" ]; then FILM_STRICT=1 cover; fi ;;
  *) echo "film: unknown step '$STEP'" >&2; usage ;;
esac
