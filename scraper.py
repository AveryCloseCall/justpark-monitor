"""
scraper.py — The "eyes" of the application.

This module is responsible for logging into JustPark and reading
the "In progress" tab to find any currently active booking.

It uses Playwright, a library that controls a real web browser
automatically — just like a human would, but invisible and instant.
"""

import os
import json
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# These are read from environment variables — secret values that you
# configure on the cloud server, so your password is never written
# directly into the code.
JUSTPARK_EMAIL    = os.environ["JUSTPARK_EMAIL"]
JUSTPARK_PASSWORD = os.environ["JUSTPARK_PASSWORD"]

BOOKINGS_URL = "https://www.justpark.com/dashboard/bookings/receive"
STATUS_FILE  = "status.json"   # Where we save the result after each check


def check_booking() -> dict:
    """
    Launches a hidden browser, logs into JustPark, and checks
    whether there is a booking currently in progress.

    Returns a dictionary with:
      - active      : True if a booking is in progress, False if not
      - until       : The end time of the active booking (if any)
      - checked_at  : The time this check was performed
      - error       : An error message if something went wrong
    """
    log.info("Starting booking check...")

    with sync_playwright() as p:
        # Launch a hidden (headless) Chromium browser
        browser = p.chromium.launch(headless=True)
        page    = browser.new_page()

        try:
            # ----------------------------------------------------------------
            # Step 1: Go to the JustPark login page
            # ----------------------------------------------------------------
            log.info("Navigating to login page...")
            page.goto("https://www.justpark.com/login", wait_until="networkidle")

            # ----------------------------------------------------------------
            # Step 2: Fill in the login form and submit it
            # ----------------------------------------------------------------
            log.info("Logging in...")
            page.fill('input[type="email"]',    JUSTPARK_EMAIL)
            page.fill('input[type="password"]', JUSTPARK_PASSWORD)
            page.click('button[type="submit"]')

            # Wait for the page to finish loading after login
            page.wait_for_load_state("networkidle")

            # ----------------------------------------------------------------
            # Step 3: Navigate to the bookings received page
            # ----------------------------------------------------------------
            log.info("Navigating to bookings page...")
            page.goto(BOOKINGS_URL, wait_until="networkidle")

            # Give any JavaScript on the page a moment to finish rendering
            page.wait_for_timeout(3000)

            # ----------------------------------------------------------------
            # Step 4: Look for booking cards on the "In progress" tab.
            # From the screenshot, each booking appears as a card.
            # We look for the "From" label which is present on every card.
            # ----------------------------------------------------------------
            log.info("Reading In Progress tab...")

            # Find all booking cards currently visible
            # (the "In progress" tab is selected by default)
            from_labels = page.locator("text=From").all()

            if len(from_labels) == 0:
                # No booking cards found — space is free
                log.info("No active booking found.")
                result = {
                    "active":     False,
                    "until":      None,
                    "checked_at": datetime.now().isoformat(),
                    "error":      None
                }
            else:
                # At least one booking card found — space is booked
                # Try to extract the "Until" time from the first card
                until_text = None
                try:
                    # Find the element after the "Until" label
                    until_element = page.locator("text=Until").first
                    # The time is in the next sibling element
                    until_text = until_element.locator("xpath=following-sibling::*[1]").inner_text()
                except Exception:
                    until_text = "Unknown"

                log.info(f"Active booking found. Until: {until_text}")
                result = {
                    "active":     True,
                    "until":      until_text,
                    "checked_at": datetime.now().isoformat(),
                    "error":      None
                }

        except PlaywrightTimeout:
            log.error("Timed out waiting for JustPark to load.")
            result = {
                "active":     None,
                "until":      None,
                "checked_at": datetime.now().isoformat(),
                "error":      "Timed out — JustPark took too long to respond."
            }

        except Exception as e:
            log.error(f"Unexpected error: {e}")
            result = {
                "active":     None,
                "until":      None,
                "checked_at": datetime.now().isoformat(),
                "error":      str(e)
            }

        finally:
            browser.close()

    # Save result to a file so the web server can read it
    with open(STATUS_FILE, "w") as f:
        json.dump(result, f)
    log.info("Status saved.")

    return result


if __name__ == "__main__":
    # Allows you to test this file directly by running: python scraper.py
    print(check_booking())
