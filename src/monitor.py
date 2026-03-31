import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable

logger = logging.getLogger(__name__)

# State changes within this window after an app trigger are considered app-caused
_APP_TRIGGER_WINDOW_SECONDS = 20


async def monitor_door(
    read_state_fn: Callable[[], str],
    notify_fn: Callable[[str], None],
    log_event_fn: Callable[[str, str, str], None],
    get_last_trigger_fn: Callable[[], datetime | None],
    interval_seconds: int = 30,
    alert_minutes: int = 10,
    mock: bool = False,
):
    prefix = "[MOCK] " if mock else ""
    prev_state: str | None = None
    door_opened_at: datetime | None = None
    last_alert_at: datetime | None = None

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            state = read_state_fn()

            # --- State change detection ---
            if prev_state is not None and state != prev_state:
                last_trigger = get_last_trigger_fn()
                is_physical = (
                    last_trigger is None
                    or (datetime.utcnow() - last_trigger).total_seconds() > _APP_TRIGGER_WINDOW_SECONDS
                )
                source = "physical" if is_physical else "app"
                logger.info(f"door state changed: {prev_state} → {state} ({source})")
                log_event_fn(source, "state_change", state)
                if is_physical:
                    notify_fn(f"{prefix}Garage door {state.upper()} (physical trigger)")

            prev_state = state

            # --- Open-door alert ---
            if state == "open":
                if door_opened_at is None:
                    door_opened_at = datetime.utcnow()
                    last_alert_at = None
                else:
                    elapsed = datetime.utcnow() - door_opened_at
                    since_last = (datetime.utcnow() - last_alert_at) if last_alert_at else elapsed
                    if elapsed >= timedelta(minutes=alert_minutes) and since_last >= timedelta(minutes=alert_minutes):
                        notify_fn(f"{prefix}Garage door has been open for {int(elapsed.total_seconds() // 60)} minutes!")
                        logger.warning(f"Door open alert sent after {elapsed}")
                        last_alert_at = datetime.utcnow()
            else:
                door_opened_at = None
                last_alert_at = None

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"monitor_door error: {e}")
