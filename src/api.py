import os
import pathlib
import logging
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, APIRouter
from fastapi.staticfiles import StaticFiles
from typing import Annotated
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
MOCK = os.getenv("MOCK", "true").lower() == "true"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")

if not MOCK:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(17, GPIO.IN)   # sensor: HIGH=open, LOW=closed
    GPIO.setup(27, GPIO.OUT, initial=GPIO.HIGH)  # relay: active LOW

app = FastAPI()
security = HTTPBearer()

# Mock state (only used when MOCK=true)
_mock_state = {"status": "closed"}

# --- Logging ---
REPO_DIR = pathlib.Path(__file__).parent.parent
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


def notify(message: str):
    if not NTFY_TOPIC:
        return
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message, timeout=5)
    except Exception as e:
        logger.error(f"ntfy notification failed: {e}")


def verify_token(credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]):
    if credentials.credentials != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def read_door_state() -> str:
    if MOCK:
        return _mock_state["status"]
    return "open" if GPIO.input(17) == GPIO.HIGH else "closed"


def pulse_relay():
    if MOCK:
        _mock_state["status"] = "open" if _mock_state["status"] == "closed" else "closed"
        return
    import time
    GPIO.output(27, GPIO.LOW)
    time.sleep(0.5)
    GPIO.output(27, GPIO.HIGH)


# --- API Routes ---

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"ok": True, "mock": MOCK}


@router.get("/status", dependencies=[Depends(verify_token)])
def get_status():
    state = read_door_state()
    logger.info(f"status checked — door is {state}")
    return {"state": state}


@router.post("/trigger", dependencies=[Depends(verify_token)])
def trigger_door():
    pulse_relay()
    state = read_door_state()
    logger.info(f"door triggered — now {state}")
    notify(f"Garage door triggered — now {state.upper()}")
    return {"triggered": True, "state": state}


app.include_router(router)

# Serve PWA static files (must be mounted last)
static_dir = pathlib.Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
