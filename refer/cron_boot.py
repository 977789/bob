from time import sleep
from requests import get as rget
from os import getenv
from logging import error as logerror, info as loginfo, basicConfig, INFO
from datetime import datetime, timedelta
import json

basicConfig(level=INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_URL = getenv("BASE_URL", None)
try:
    if not BASE_URL or len(BASE_URL) == 0:
        raise TypeError
    BASE_URL = BASE_URL.rstrip("/")
except TypeError:
    BASE_URL = None

PORT = getenv("PORT", None)
success_count = 0
fail_count = 0
consecutive_failures = 0
max_consecutive_failures = 10  # Trigger recovery after 10 consecutive failures
last_recovery_attempt = None
recovery_cooldown = 1800  # 30 minutes cooldown between recovery attempts


def attempt_recovery():
    """Attempt to recover from consecutive failures"""
    global last_recovery_attempt, consecutive_failures

    now = datetime.now()
    if (
        last_recovery_attempt
        and (now - last_recovery_attempt).seconds < recovery_cooldown
    ):
        loginfo(f"[cron_boot] Recovery cooldown active, skipping recovery attempt")
        return

    last_recovery_attempt = now
    consecutive_failures = 0  # Reset counter after recovery attempt

    logerror(
        f"[cron_boot] Attempting recovery after {max_consecutive_failures} consecutive failures"
    )

    # Try to ping a different endpoint or restart mechanism
    try:
        # You can add custom recovery logic here
        # For example, call a different endpoint or send a signal
        recovery_response = rget(f"{BASE_URL}/health", timeout=10)
        if recovery_response.status_code == 200:
            loginfo(f"[cron_boot] Recovery successful via health endpoint")
        else:
            logerror(
                f"[cron_boot] Recovery failed, health endpoint returned {recovery_response.status_code}"
            )
    except Exception as e:
        logerror(f"[cron_boot] Recovery attempt failed: {e}")


if PORT is not None and BASE_URL is not None:
    loginfo(f"[cron_boot] Starting enhanced health monitoring for {BASE_URL}")

    while True:
        try:
            response = rget(BASE_URL, timeout=30)
            if response.status_code == 200:
                success_count += 1
                consecutive_failures = 0  # Reset consecutive failures on success
                loginfo(
                    f"[cron_boot] Ping successful. Total successful pings: {success_count}"
                )
            else:
                fail_count += 1
                consecutive_failures += 1
                logerror(
                    f"[cron_boot] Ping failed with status {response.status_code}. "
                    f"Total fails: {fail_count}, Consecutive: {consecutive_failures}"
                )

                # Attempt recovery if too many consecutive failures
                if consecutive_failures >= max_consecutive_failures:
                    attempt_recovery()

            sleep(300)  # 5 minutes
        except Exception as e:
            fail_count += 1
            consecutive_failures += 1
            logerror(
                f"[cron_boot] Exception: {e}. Total fails: {fail_count}, Consecutive: {consecutive_failures}"
            )

            # Attempt recovery if too many consecutive failures
            if consecutive_failures >= max_consecutive_failures:
                attempt_recovery()

            sleep(10)
            continue
else:
    loginfo("[cron_boot] BASE_URL or PORT not configured, health monitoring disabled")
