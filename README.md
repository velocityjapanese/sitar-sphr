# SitarSpheric

Daily original cinematic sitar & piano suites for focus, meditation and sleep.
Every video is composed, rendered and scored from scratch in 1080p.

**Channel:** https://www.youtube.com/channel/UCWjSgxl4R4wxJImvusUyDgg

## What each video contains

- A real CC0 photograph of a Metropolitan Museum sitar (object 502150), cut out
  and lit on a dark stage.
- A new original composition in a different key, tempo and movement structure
  each day, with a sitar melody over a felt piano.
- A synced cream-paper score with a moving playback cursor and blue note glow.
- A thumbnail generated from a real frame of the render.

## How it works

| File | Purpose |
| --- | --- |
| `composition.py` | Generates the MIDI score, key/tempo/movement map and titles. |
| `audio.py` | Renders the sitar stem with MuseScore General program 104 and the piano with Salamander. |
| `render/` | Builds the stage, sitar strip, glowing playing points, paper score and cursor. |
| `bot.py` | End-to-end renderer; writes the MP4, hero frame, chapters and metadata. |
| `auto_pipeline.py` | Daily orchestrator: render, thumbnail, SEO metadata, YouTube/Facebook upload. |
| `thumbnail_generator.py` | 1280x720 thumbnail layout. |
| `scripts/` | One-off channel branding and GitHub secret helpers. |

## Local render

```powershell
pip install -r requirements.txt
python bot.py --minutes 15 --seed 20261125 --workers 4
```

A shorter preview:

```powershell
python bot.py --minutes 2 --seed 20261125 --output SitarSpheric_sample.mp4
```

FluidSynth and ffmpeg must be on `PATH`. The soundfonts are fetched by CI and are
not committed.

## Publishing

The GitHub Actions workflow `.github/workflows/daily_sitar.yml` runs daily at
08:00 UTC. It renders a new 15-minute suite, generates the thumbnail and
metadata, uploads to YouTube, and commits `published_videos.json`.

Required repository secrets:

- `YT_CLIENT_ID`
- `YT_CLIENT_SECRET`
- `YT_REFRESH_TOKEN`
- `CHANNEL_NAME` (`SitarSpheric`)
- `POLLINATIONS_API_KEY` (optional; deterministic metadata is used without it)

The channel avatar has no API endpoint and must be uploaded manually in YouTube
Studio. The source file is `branding/channel_avatar_800.png`.

## Credits

- Sitar photograph: The Metropolitan Museum of Art, "Sitar", late 19th century,
  The Crosby Brown Collection of Musical Instruments, 1889 (89.4.1586).
  CC0 1.0 Open Access. https://www.metmuseum.org/art/collection/search/502150
- Sitar patch: MuseScore General (program 104, Sitar).
- Piano: Salamander Grand Piano.
- All compositions and renders are original to this channel.
