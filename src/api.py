import os
import pathlib
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, APIRouter
from fastapi.staticfiles import StaticFiles
from typing import Annotated
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
MOCK = os.getenv("MOCK", "true").lower() == "true"

if not MOCK:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(17, GPIO.IN)   # sensor: HIGH=open, LOW=closed
    GPIO.setup(27, GPIO.OUT, initial=GPIO.HIGH)  # relay: active LOW

app = FastAPI()
security = HTTPBearer()

# Mock state (only used when MOCK=true)
_mock_state = {"status": "closed"}


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
    return {"state": read_door_state()}


@router.post("/trigger", dependencies=[Depends(verify_token)])
def trigger_door():
    pulse_relay()
    return {"triggered": True, "state": read_door_state()}


app.include_router(router)

# Serve PWA static files (must be mounted last)
static_dir = pathlib.Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
