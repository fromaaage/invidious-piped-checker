# Invidious & Piped Checker

Finds public Invidious and Piped instances that are actually alive, lets you test them in your own browser, and remembers the ones that work for you.

![Screenshot](docs/screenshot.png)

## Why

Most public instances listed online are dead, have their API disabled, or are blocked by YouTube. Many of the remaining sites sit behind bot checks (captchas) that keep automated players out, so a script can't reliably tell whether a video will play. This tool automates everything up to that point and leaves the final playback test to you.

## How it works

1. Collects instances from [api.invidious.io](https://api.invidious.io), the [Piped docs](https://github.com/TeamPiped/documentation/blob/main/content/docs/public-instances/index.md), [piped-uptime](https://github.com/TeamPiped/piped-uptime), [LibRedirect](https://github.com/libredirect/instances) and [Farside](https://github.com/benbusby/farside), and merges duplicates.
2. Tests each one in parallel:
   - **API**: fetches a real video, runs a search, and checks that the stream delivers bytes (what apps like Yattee, FreeTube or NewPipe need).
   - **Website**: checks whether the site responds. Bot-check pages count as online.
3. Shows the live sites. **Test** opens a short video in your default browser, and **Works** or **Broken** saves your verdict.
4. **Watch YouTube** opens your best working favorite.

The bot checks are not bypassed. Playback has to be confirmed by you.

## Requirements

- Python ≥ 3.10
- PySide6 (Qt 6) and requests

```sh
# Arch
sudo pacman -S pyside6 python-requests
# others
pip install PySide6 requests
```

## Usage

```sh
python app.py                 # GUI, starts checking right away
python app.py --no-autoscan   # GUI without the automatic check
python core.py                # CLI table
python core.py --json         # CLI, JSON output
```

Your marks and custom instances are stored in `~/.config/invidious-piped-checker/`.
