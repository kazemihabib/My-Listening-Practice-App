#!/usr/bin/env python3
"""
Listening Practice App
Type what you hear, chunk by chunk. Compare to the correct text and repeat or move on.
"""

import sys
import os
import re
import subprocess
import tempfile
import argparse
import difflib
import json

try:
    import gnureadline as readline
except ImportError:
    import readline
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path.home() / ".config" / "listen" / "config.json"

DEFAULTS: dict = {
    "model": "mlx-community/whisper-large-v3-turbo",
    "language": None,
    "min_words": 6,
    "max_words": 30,
    "max_duration": 15.0,
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return {**DEFAULTS, **json.loads(CONFIG_PATH.read_text())}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULTS)


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    print(f"{DIM}Config saved → {CONFIG_PATH}{RESET}")


import mlx_whisper
from pydub import AudioSegment

# ── ANSI colors ────────────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
WHITE = "\033[97m"


def rl(code: str) -> str:
    """Wrap an ANSI escape code so readline doesn't count it toward line width."""
    return f"\001{code}\002"


DIVIDER = f"{DIM}{'─' * 50}{RESET}"


def clear() -> None:
    print("\033[2J\033[H", end="", flush=True)


def print_header(current: int, total: int, filename: str) -> None:
    bar_width = 40
    filled = round(bar_width * current / total)
    bar = f"{CYAN}{'█' * filled}{DIM}{'░' * (bar_width - filled)}{RESET}"
    print(f"{BOLD}Listening Practice{RESET}  {DIM}{filename}{RESET}")
    print(f"[{bar}]  {BOLD}{current}{RESET}{DIM}/{total}{RESET}")
    print()


def normalize(text: str) -> list[str]:
    """Lowercase and strip punctuation, return list of words."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s']", "", text)
    return text.split()


def show_comparison(user_text: str, correct_text: str) -> None:
    """
    Word-by-word diff between what the user typed and the correct text.
    Green  = correct word
    Red    = wrong / extra word (in user's answer)
    Yellow = missed word (in correct answer)
    """
    user_words = normalize(user_text)
    correct_words = normalize(correct_text)

    matcher = difflib.SequenceMatcher(None, user_words, correct_words, autojunk=False)
    opcodes = matcher.get_opcodes()

    # Build colored user line
    user_colored: list[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            user_colored += [f"{GREEN}{w}{RESET}" for w in user_words[i1:i2]]
        elif tag in ("replace", "delete"):
            user_colored += [f"{RED}{w}{RESET}" for w in user_words[i1:i2]]
        # insertions don't appear in user's output

    # Build colored correct line
    correct_colored: list[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            correct_colored += [f"{GREEN}{w}{RESET}" for w in correct_words[j1:j2]]
        elif tag in ("replace", "insert"):
            correct_colored += [f"{YELLOW}{w}{RESET}" for w in correct_words[j1:j2]]

    # Accuracy
    correct_count = sum(i2 - i1 for tag, i1, i2, _, __ in opcodes if tag == "equal")
    total_words = len(correct_words)
    accuracy = (correct_count / total_words * 100) if total_words else 0

    print(f"{BOLD}Your answer:{RESET}")
    print(" ".join(user_colored) if user_colored else f"{DIM}(nothing typed){RESET}")
    print()
    print(f"{BOLD}Correct:{RESET}")
    print(correct_text.strip())
    print()

    if accuracy == 100:
        print(f"{GREEN}{BOLD}Perfect! ✓{RESET}")
    else:
        bar_len = 20
        filled = round(bar_len * accuracy / 100)
        acc_bar = f"{GREEN}{'█' * filled}{DIM}{'░' * (bar_len - filled)}{RESET}"
        print(f"Accuracy  [{acc_bar}]  {BOLD}{accuracy:.0f}%{RESET}")


def build_chunks(
    segments: list[dict],
    min_words: int = 6,
    max_words: int = 30,
    max_duration: float = 15.0,
) -> list[dict]:
    """
    Merge Whisper segments into natural practice chunks.

    Strategy:
    - Prefer ending a chunk at a sentence boundary (.!?) when it has ≥ min_words.
    - Always split before exceeding max_words or max_duration.
    - Merge tiny segments forward so no chunk is embarrassingly short.
    """
    chunks: list[dict] = []
    current: dict | None = None

    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue

        wc = len(text.split())

        if current is None:
            current = {
                "text": text,
                "start": seg["start"],
                "end": seg["end"],
                "words": wc,
            }
            continue

        merged_duration = seg["end"] - current["start"]
        merged_words = current["words"] + wc
        ends_sentence = current["text"].rstrip()[-1] in ".!?"

        if merged_words > max_words or merged_duration > max_duration:
            # Hard limit – emit current and start fresh
            chunks.append(current)
            current = {
                "text": text,
                "start": seg["start"],
                "end": seg["end"],
                "words": wc,
            }
        elif ends_sentence and current["words"] >= min_words:
            # Natural sentence boundary with enough content – good stopping point
            chunks.append(current)
            current = {
                "text": text,
                "start": seg["start"],
                "end": seg["end"],
                "words": wc,
            }
        else:
            # Keep merging
            current["text"] += " " + text
            current["end"] = seg["end"]
            current["words"] = merged_words

    if current:
        chunks.append(current)

    return chunks


def extract_chunk_audio(
    audio: AudioSegment,
    start_s: float,
    end_s: float,
    padding_ms: int = 400,
) -> AudioSegment:
    start_ms = max(0, int(start_s * 1000) - padding_ms)
    end_ms = min(len(audio), int(end_s * 1000) + padding_ms)
    return audio[start_ms:end_ms]


def play(path: str) -> None:
    """Play an audio file synchronously (blocks until done)."""
    subprocess.run(["afplay", path], check=True)


def play_async(path: str) -> subprocess.Popen:
    """Start playback in the background; returns the process so it can be killed."""
    return subprocess.Popen(["afplay", path])


def input_prefilled(prompt: str, prefill: str = "") -> str:
    """Show an input prompt with text already filled in, ready to be edited."""
    readline.set_startup_hook(lambda: readline.insert_text(prefill))
    try:
        return input(prompt)
    finally:
        readline.set_startup_hook(None)


def play_and_ask(chunk_path: str, i: int, total: int, filename: str) -> str | None:
    """
    Play the chunk and prompt the user to type what they heard.
    Typing /r anywhere replays the audio and restores whatever was typed
    before /r so the user can continue from where they left off.
    Returns the user's answer, or None if they quit (Ctrl-C / EOF).
    """
    prefill = ""
    while True:
        clear()
        print_header(i + 1, total, filename)
        print(f"{CYAN}► Playing…{RESET}  {DIM}(type /r anywhere to replay){RESET}\n")
        proc = play_async(chunk_path)
        try:
            user_input = input_prefilled(
                f"{rl(BOLD)}Type what you heard:{rl(RESET)}  ", prefill
            )
        except (KeyboardInterrupt, EOFError):
            proc.kill()
            return None

        proc.kill()  # stop audio if still running after Enter

        # Check for /r anywhere in the input
        if re.search(r"/r", user_input, re.IGNORECASE):
            # Remove /r (and any surrounding whitespace) and keep the rest
            prefill = re.sub(r"\s*/r\s*", " ", user_input, flags=re.IGNORECASE).strip()
            continue

        return user_input


def export_chunk(chunk_audio: AudioSegment, path: str) -> None:
    """Export a chunk to disk once; skip if already done."""
    if not os.path.exists(path):
        chunk_audio.export(path, format="mp3")


# ── Core practice loop ─────────────────────────────────────────────────────────


def practice(
    audio_path: str,
    start_chunk: int = 0,
    model: str = DEFAULTS["model"],
    language: str | None = None,
    min_words: int = DEFAULTS["min_words"],
    max_words: int = DEFAULTS["max_words"],
    max_duration: float = DEFAULTS["max_duration"],
) -> None:
    audio_file = Path(audio_path)
    if not audio_file.exists():
        print(f"{RED}Error: file not found – {audio_path}{RESET}")
        sys.exit(1)

    clear()
    print(f"{BOLD}Listening Practice{RESET}\n")
    print(f"File     : {CYAN}{audio_file.name}{RESET}")
    print(f"Model    : {DIM}{model}{RESET}")
    print(f"Language : {DIM}{language if language else 'auto-detect'}{RESET}")
    print(f"Chunks   : {DIM}{min_words}–{max_words} words, ≤{max_duration}s{RESET}\n")

    # ── Load ──────────────────────────────────────────────────────────────────
    print(f"Loading audio…")
    audio = AudioSegment.from_file(audio_path)
    duration_s = len(audio) / 1000
    print(f"Duration: {duration_s:.0f}s\n")

    # ── Transcribe (with cache) ────────────────────────────────────────────────
    cache_path = audio_file.with_suffix(".chunks.json")
    chunks: list[dict] = []

    if cache_path.exists():
        print(f"{CYAN}Found saved transcript:{RESET} {DIM}{cache_path.name}{RESET}")
        try:
            cached = json.loads(cache_path.read_text())
            preview = cached[0]["text"][:60] + (
                "…" if len(cached[0]["text"]) > 60 else ""
            )
            print(f'{DIM}First chunk: "{preview}"{RESET}')
            print(
                f"\nUse this transcript?  {BOLD}[y]{RESET} Yes   {BOLD}[n]{RESET} Regenerate  ",
                end="",
                flush=True,
            )
            answer = input().strip().lower()
            if answer != "n":
                chunks = cached
                print(f"{GREEN}✓ Loaded {len(chunks)} chunks from cache.{RESET}\n")
        except (json.JSONDecodeError, KeyError):
            print(f"{YELLOW}Cache file looks corrupt – regenerating.{RESET}\n")

    if not chunks:
        print(f"Transcribing with Whisper (this may take a moment)…")
        result = mlx_whisper.transcribe(
            audio_path,
            path_or_hf_repo=model,
            word_timestamps=True,
            verbose=False,
            language=language,
        )
        segments = result.get("segments", [])

        if not segments:
            print(f"{RED}No speech detected in the audio file.{RESET}")
            sys.exit(1)

        chunks = build_chunks(
            segments,
            min_words=min_words,
            max_words=max_words,
            max_duration=max_duration,
        )
        print(f"{GREEN}✓ Transcription complete – {len(chunks)} chunks ready.{RESET}")

        print(
            f"\nSave transcript for next time?  {BOLD}[y]{RESET} Yes   {BOLD}[n]{RESET} No  ",
            end="",
            flush=True,
        )
        if input().strip().lower() == "y":
            cache_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2))
            print(f"{DIM}Saved → {cache_path.name}{RESET}")
        print()

    total = len(chunks)

    if start_chunk >= total:
        print(
            f"{YELLOW}--start {start_chunk} is out of range (only {total} chunks).{RESET}"
        )
        sys.exit(1)

    print(f"Press {BOLD}Enter{RESET} to start…")
    input()

    with tempfile.TemporaryDirectory() as tmp:
        i = start_chunk

        while i < total:
            chunk = chunks[i]
            chunk_path = os.path.join(tmp, f"chunk_{i:04d}.mp3")
            chunk_audio = extract_chunk_audio(audio, chunk["start"], chunk["end"])
            export_chunk(chunk_audio, chunk_path)

            # ── Play → ask ─────────────────────────────────────────────────
            user_input = play_and_ask(chunk_path, i, total, audio_file.name)
            if user_input is None:
                break

            # ── Show result ────────────────────────────────────────────────
            def show_result() -> None:
                clear()
                print_header(i + 1, total, audio_file.name)
                show_comparison(user_input, chunk["text"])
                print()
                print(DIVIDER)
                print(
                    f"  {CYAN}[/r]{RESET} Listen again   {CYAN}[r]{RESET} Retry"
                    f"   {CYAN}[n/↵]{RESET} Next   {CYAN}[p]{RESET} Previous"
                    f"   {CYAN}[1-{total}]{RESET} Jump   {CYAN}[q]{RESET} Quit"
                )
                print(DIVIDER)

            show_result()

            # ── Wait for command ───────────────────────────────────────────
            while True:
                try:
                    key = input().strip().lower()
                except (KeyboardInterrupt, EOFError):
                    key = "q"

                if key == "/r":
                    play(chunk_path)
                    show_result()

                elif key == "r":
                    user_input = play_and_ask(chunk_path, i, total, audio_file.name)
                    if user_input is None:
                        key = "q"
                        break
                    show_result()

                elif key in ("n", ""):
                    i += 1
                    break

                elif key == "p":
                    i = max(0, i - 1)
                    break

                elif key.isdigit() or (key[1:].isdigit() if len(key) > 1 else False):
                    target = int(key) - 1  # user types 1-based chunk number
                    if 0 <= target < total:
                        i = target
                        break
                    else:
                        print(f"{YELLOW}Enter a number between 1 and {total}.{RESET}")

                elif key == "q":
                    clear()
                    print(
                        f"\n{YELLOW}Session ended.{RESET}  Completed {BOLD}{i}{RESET}/{total} chunks."
                    )
                    print(
                        f"Resume later with  {DIM}uv run app.py {audio_path} --start {i}{RESET}\n"
                    )
                    return

                # any other input → wait again

    clear()
    print(
        f"\n{GREEN}{BOLD}Practice complete!{RESET}  You worked through all {total} chunks."
    )
    print(f"{DIM}Keep it up!{RESET}\n")


# ── CLI ────────────────────────────────────────────────────────────────────────


def main() -> None:
    cfg = load_config()

    parser = argparse.ArgumentParser(
        prog="listen",
        description="Listening practice – type what you hear, chunk by chunk.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Current config ({CONFIG_PATH}):
  model        = {cfg["model"]}
  language     = {cfg["language"] or "auto-detect"}
  min_words    = {cfg["min_words"]}
  max_words    = {cfg["max_words"]}
  max_duration = {cfg["max_duration"]}s

Examples:
  listen podcast.mp3
  listen lesson.m4a --language it --save-config
  listen talk.mp3 --max-words 15 --max-duration 8
        """,
    )
    parser.add_argument("audio", help="Audio file to practice with (mp3, m4a, wav, …)")
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        metavar="N",
        help="Resume from chunk N (default: 0)",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help=f"Whisper model (config: {cfg['model']})",
    )
    parser.add_argument(
        "--language",
        default=None,
        metavar="LANG",
        help=f"Language code, e.g. it, en, fr (config: {cfg['language'] or 'auto-detect'})",
    )
    parser.add_argument(
        "--min-words",
        type=int,
        default=None,
        metavar="N",
        help=f"Minimum words per chunk (config: {cfg['min_words']})",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=None,
        metavar="N",
        help=f"Maximum words per chunk (config: {cfg['max_words']})",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=None,
        metavar="SEC",
        help=f"Maximum chunk duration in seconds (config: {cfg['max_duration']})",
    )
    parser.add_argument(
        "--save-config",
        action="store_true",
        help="Save current options as the new defaults",
    )
    args = parser.parse_args()

    # CLI overrides config; config overrides hardcoded defaults
    model = args.model or cfg["model"]
    language = args.language or cfg["language"]
    min_words = args.min_words if args.min_words is not None else cfg["min_words"]
    max_words = args.max_words if args.max_words is not None else cfg["max_words"]
    max_duration = (
        args.max_duration if args.max_duration is not None else cfg["max_duration"]
    )

    if args.save_config:
        save_config(
            {
                "model": model,
                "language": language,
                "min_words": min_words,
                "max_words": max_words,
                "max_duration": max_duration,
            }
        )

    practice(
        args.audio, args.start, model, language, min_words, max_words, max_duration
    )


if __name__ == "__main__":
    main()
