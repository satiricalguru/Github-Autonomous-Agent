#!/usr/bin/env bash
# Stitches frames from capture_readme_media.mjs into README GIFs and an MP4, then removes the frames.
# Usage: scripts/build_readme_media.sh [mediaDir]
set -euo pipefail
DIR="${1:-docs/media}"
cd "$DIR"

gif() { # frames-dir out.gif fps width
  ffmpeg -loglevel error -y -framerate "$3" -i "$1/f%04d.jpg" \
    -vf "scale=$4:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
    "$2"
}

# Hero: particles assemble into the GitHub mark.
gif frames-intro hero-intro.gif 12 800
# Homepage scroll-through: the field morphs per section.
gif frames-scroll home-scroll.gif 10 720
# Dashboard scroll-through.
gif frames-dashboard dashboard-tour.gif 9 760

# Full-quality video of the homepage scroll for GitHub's inline player.
ffmpeg -loglevel error -y -framerate 24 -i frames-scroll/f%04d.jpg -c:v libx264 -pix_fmt yuv420p -crf 26 -movflags +faststart -vf "scale=1280:-2" home-scroll.mp4

rm -rf frames-intro frames-scroll frames-dashboard
ls -lh *.gif *.mp4
