# Listening Practice App

> **Personal project, macOS only.** Built for personal use on Apple Silicon, mostly with AI assistance. Licensed under [MIT](LICENSE). Feel free to use or adapt it, but don't expect support, maintenance, or updates.

A terminal app to improve listening comprehension. It splits an audio file into natural chunks using Whisper, plays each chunk, and asks you to type what you heard. You then see a word-by-word comparison with the correct transcript.

## Requirements

- macOS with Apple Silicon (M1/M2/M3/…)
- [`uv`](https://docs.astral.sh/uv/) package manager

> The app relies on `afplay` (macOS built-in) for audio playback and `mlx-whisper` (Apple's MLX framework) for transcription. Neither works outside macOS on Apple Silicon.

## How it works

1. **Transcribe** – Whisper (running locally via MLX) transcribes the audio and produces timestamped segments.
2. **Chunk** – Segments are merged into natural practice chunks at sentence boundaries.
3. **Practice loop** – For each chunk:
   - The audio plays automatically.
   - You type what you heard and press Enter.
   - Your answer is compared word-by-word to the correct text:
     - **Green** = correct word
     - **Red** = wrong or extra word (in your answer)
     - Missed words are shown in the correct line

## Installation

```bash
uv tool install /path/to/my_listening_app
```

## Usage

```bash
# Basic
listen podcast.mp3

# Resume from chunk 10
listen lesson.m4a --start 10

# Specify language (faster + more accurate transcription)
listen audio.mp3 --language it

# Tighter chunks
listen audio.mp3 --max-words 15 --max-duration 8

# Save current options as your new defaults
listen audio.mp3 --language it --max-words 20 --save-config

# Or run directly without installing
uv run app.py podcast.mp3
```

## Controls

| Key | Action |
|---|---|
| `/r` | Listen again (audio only, no re-typing) |
| `r` | Retry (replay audio and type again) |
| `/r` while typing | Replay audio, keep what you've typed so far |
| `n` / Enter | Next chunk |
| `p` | Previous chunk |
| `1`…`N` | Jump to chunk number |
| `q` | Quit |

## Options

| Flag | Default | Description |
|---|---|---|
| `--language LANG` | auto-detect | Language code: `it`, `en`, `fr`, `de`, … |
| `--model MODEL` | `whisper-large-v3-turbo` | Whisper model to use |
| `--min-words N` | `6` | Minimum words before a chunk can end |
| `--max-words N` | `30` | Maximum words per chunk |
| `--max-duration SEC` | `15.0` | Maximum chunk length in seconds |
| `--start N` | `0` | Resume from chunk N |
| `--save-config` | — | Save current options as permanent defaults |

Config is stored at `~/.config/listen/config.json`. Run `listen --help` to see your current saved values.

## Transcript cache

On first run you'll be asked whether to save the transcript. If saved, a `.chunks.json` file is placed next to the audio file. On subsequent runs you'll be prompted to use the cached version or regenerate.

## Models

| Model | Speed | Accuracy |
|---|---|---|
| `mlx-community/whisper-large-v3-turbo` | fast | excellent (default) |
| `mlx-community/whisper-small-mlx` | very fast | good |
| `mlx-community/whisper-base-mlx` | fastest | moderate |

Models are downloaded automatically on first use from Hugging Face.

## License

[MIT](LICENSE) © Habib Kazemi
