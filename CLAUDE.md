# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
# Local dev (mock mode, no hardware needed)
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt   # runtime + test deps
python3 -m uvicorn src.api:app --reload

# Production (Pi)
sudo systemctl restart smart-garage
sudo journalctl -u smart-garage -f
tail -f ~/projects/smart-garage/garage.log
```

Requires a `.env` file — copy from `.env.example` and fill in `API_TOKEN`, `NTFY_TOPIC`, set `MOCK=true` for local dev.

## Testing

Test deps (`pytest`, `httpx`) live in `requirements-dev.txt`, separate from runtime deps in `requirements.txt`. Install both, then:

```bash
pip install -r requirements-dev.txt
pytest   # 28 tests
```

## Architecture

Two processes run inside FastAPI's lifespan:
1. **`src/monitor.py` `monitor_door()`** — asyncio task. In mock mode (`detect_changes=True`), polls door state every second and handles both state-change notifications and the "open for N minutes" repeating alert. In real hardware mode (`detect_changes=False`), only handles the repeating alert — state changes come from the GPIO thread.
2. **`_gpio_poll_thread()`** (real hardware only) — daemon thread in `src/api.py` that polls GPIO 17 every 50ms with a 10-read (500ms) software debounce. Calls `_on_state_change()` on confirmed transitions. Replaces `GPIO.add_event_detect` which is unreliable on this Pi OS version.

### Modes

| Env var | Effect |
|---------|--------|
| `MOCK=true` | No GPIO imports; simulates door state and random physical events |
| `TEST=true` | Real GPIO; logs `[TEST] would notify: ...` instead of posting to ntfy.sh; relaxes `NTFY_TOPIC` requirement |
| `MOCK=false, TEST=false` | Full production: real GPIO + real ntfy notifications |

### GPIO Hardware
- **Pin 17**: Sensor input, `PUD_UP` pull-up. HIGH=open, LOW=closed. Sensor wired between pin and GND — floats (and must be pulled up) when door is open.
- **Pin 27**: Relay output, active LOW. Pulsed LOW for 500ms to trigger door.

### App vs Physical Source Heuristic
State changes within 20 seconds of an app trigger (`_trigger_time["at"]`) are labelled `"app"`. All others are `"physical"`. Only physical changes send ntfy notifications.

### Auth
Bearer token validated against `USERS` dict. Loaded from `users.json` (token → display name) if present, otherwise falls back to `{API_TOKEN: "Owner"}`.

### Database
SQLite `garage.db`, table `events(id, timestamp, user, action, state)`. `action` is either `"trigger"` (user pressed button) or `"state_change"` (door moved). `user` is the display name for triggers, or `"physical"`/`"app"` for state changes.

### PWA
Single `index.html` — no build step. Polls `/api/status` every 5 seconds. Token stored in `localStorage`. Service worker enables installation only (no caching).

## Deployment (Pi)

```bash
bash deploy/setup.sh   # first-time only: creates venv, installs deps, registers systemd service
```

Access at `http://<hostname>.local:8000`.

## Git Workflow

Commit to `dev` branch; merge to `main` only when the user explicitly asks.
