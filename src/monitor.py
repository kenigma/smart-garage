import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable

logger = logging.getLogger(__name__)


async def monitor_door(
    read_state_fn: Callable[[], str],
    notify_fn: Callable[[str], None],
    interval_seconds: int = 30,
    alert_minutes: int = 10,
):
    door_opened_at: datetime | None = None
    last_alert_at: datetime | None = None

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            state = read_state_fn()

            if state == "open":
                if door_opened_at is None:
                    door_opened_at = datetime.utcnow()
                    last_alert_at = None
                else:
                    elapsed = datetime.utcnow() - door_opened_at
                    since_last = (datetime.utcnow() - last_alert_at) if last_alert_at else elapsed
                    if elapsed >= timedelta(minutes=alert_minutes) and since_last >= timedelta(minutes=alert_minutes):
                        notify_fn(f"Garage door has been open for {int(elapsed.total_seconds() // 60)} minutes!")
                        logger.warning(f"Door open alert sent after {elapsed}")
                        last_alert_at = datetime.utcnow()
            else:
                door_opened_at = None
                last_alert_at = None

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"monitor_door error: {e}")
