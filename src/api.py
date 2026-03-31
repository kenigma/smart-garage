import os
import json
import sqlite3
import pathlib
import logging
import requests
from contextlib import asynccontextmanager
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, APIRouter
from fastapi.staticfiles import StaticFiles
from typing import Annotated
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
MOCK = os.getenv("MOCK", "true").lower() == "true"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
DOOR_OPEN_ALERT_MINUTES = int(os.getenv("DOOR_OPEN_ALERT_MINUTES", "10"))

if not NTFY_TOPIC:
    import sys
    logging.basicConfig(level=logging.ERROR)
    logging.error("NTFY_TOPIC is not set in .env — notifications are required. Exiting.")
    sys.exit(1)

REPO_DIR = pathlib.Path(__file__).parent.parent
VERSION = (REPO_DIR / "VERSION").read_text().strip()

# --- User loading ---
_users_file = REPO_DIR / "users.json"
if _users_file.exists():
    with open(_users_file) as f:
        USERS: dict[str, str] = json.load(f)
else:
    USERS = {API_TOKEN: "Owner"} if API_TOKEN else {}

if not MOCK:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(17, GPIO.IN)   # sensor: HIGH=open, LOW=closed
    GPIO.setup(27, GPIO.OUT, initial=GPIO.HIGH)  # relay: active LOW

# --- Logging ---
log_path = REPO_DIR / "garage.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_path),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# --- SQLite history ---
DB_PATH = REPO_DIR / "garage.db"


def _init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS events "
        "(id INTEGER PRIMARY KEY, timestamp TEXT, user TEXT, action TEXT, state TEXT)"
    )
    con.commit()
    con.close()


def _log_event(user: str, action: str, state: str):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO events (timestamp, user, action, state) VALUES (?, ?, ?, ?)",
        (datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), user, action, state),
    )
    con.commit()
    con.close()


_init_db()


# --- ntfy ---
def notify(message: str):
    if not NTFY_TOPIC:
        return
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message, timeout=5)
    except Exception as e:
        logger.error(f"ntfy notification failed: {e}")


# --- Auth ---
security = HTTPBearer()


def verify_token(credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]) -> str:
    if credentials.credentials not in USERS:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return USERS[credentials.credentials]


# --- Hardware ---
_mock_state = {"status": "closed"}
_trigger_time: dict = {"at": None}  # tracks last app-triggered time


def read_door_state() -> str:
    if MOCK:
        return _mock_state["status"]
    return "open" if GPIO.input(17) == GPIO.HIGH else "closed"


def pulse_relay():
    if MOCK:
        import threading
        def _toggle():
            _mock_state["status"] = "open" if _mock_state["status"] == "closed" else "closed"
        threading.Timer(7, _toggle).start()
        return
    import time
    GPIO.output(27, GPIO.LOW)
    time.sleep(0.5)
    GPIO.output(27, GPIO.HIGH)


# --- Lifespan (door monitor + mock physical events) ---
@asynccontextmanager
async def lifespan(app):
    import asyncio
    from src.monitor import monitor_door
    tasks = [
        asyncio.create_task(
            monitor_door(
                read_door_state, notify, _log_event,
                lambda: _trigger_time["at"],
                interval_seconds=1, alert_minutes=DOOR_OPEN_ALERT_MINUTES, mock=MOCK,
            )
        )
    ]
    if MOCK:
        tasks.append(asyncio.create_task(_mock_physical_events()))
    yield
    for t in tasks:
        t.cancel()


async def _mock_physical_events():
    import asyncio
    import random
    while True:
        await asyncio.sleep(random.randint(60, 180))
        _mock_state["status"] = "open" if _mock_state["status"] == "closed" else "closed"
        logger.info(f"[mock] physical event — door now {_mock_state['status']}")


app = FastAPI(lifespan=lifespan)
router = APIRouter(prefix="/api")


# --- Routes ---

@router.get("/health")
def health():
    return {"ok": True, "mock": MOCK, "version": VERSION}


@router.get("/status", dependencies=[Depends(verify_token)])
def get_status():
    state = read_door_state()
    logger.info(f"status checked — door is {state}")
    return {"state": state}


@router.post("/trigger")
def trigger_door(user: str = Depends(verify_token)):
    before_state = read_door_state()
    logger.info(f"{user} triggered door — was {before_state}")
    _log_event(user, "trigger", before_state)
    pulse_relay()
    _trigger_time["at"] = datetime.utcnow()
    logger.info("trigger done")
    return {"triggered": True}


@router.get("/history", dependencies=[Depends(verify_token)])
def get_history(limit: int = 50):
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT timestamp, user, action, state FROM events ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    con.close()
    return [{"timestamp": r[0], "user": r[1], "action": r[2], "state": r[3]} for r in rows]


app.include_router(router)

# Serve PWA static files (must be mounted last)
static_dir = pathlib.Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
