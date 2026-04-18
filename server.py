"""
server.py — The "face" of the application.

This module runs a small web server that:
  1. Serves the status page to your browser / phone
  2. Accepts a manual "Refresh Now" request
  3. Runs the 15-minute automatic check in the background

Think of it as the front desk — it receives your requests and
coordinates with the scraper to get you an answer.
"""

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string

from scraper import check_booking, STATUS_FILE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# A lock prevents two checks running at the same time
# (e.g. if a manual refresh is triggered just as the automatic one fires)
check_lock = threading.Lock()


def read_status() -> dict:
    """Read the last saved status from disk, or return a default if none exists yet."""
    path = Path(STATUS_FILE)
    if not path.exists():
        return {
            "active":     None,
            "until":      None,
            "checked_at": None,
            "error":      "No check has been run yet."
        }
    with open(path) as f:
        return json.load(f)


def run_check():
    """Run a booking check, but only if one isn't already running."""
    if check_lock.acquire(blocking=False):
        try:
            check_booking()
        finally:
            check_lock.release()
    else:
        log.info("Check already in progress, skipping.")


def format_checked_at(iso_string: str | None) -> str:
    """Turn an ISO timestamp into a friendly string like '2 minutes ago'."""
    if not iso_string:
        return "Never"
    try:
        checked = datetime.fromisoformat(iso_string)
        now     = datetime.now()
        diff    = int((now - checked).total_seconds())

        if diff < 60:
            return f"{diff} seconds ago"
        elif diff < 3600:
            return f"{diff // 60} minutes ago"
        else:
            return f"{diff // 3600} hours ago"
    except Exception:
        return iso_string


# ============================================================
# The HTML page — this is what you see on your phone / browser
# ============================================================
PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Parking Space Monitor</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f0f2f5;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }

    .card {
      background: white;
      border-radius: 20px;
      padding: 40px 32px;
      max-width: 380px;
      width: 100%;
      text-align: center;
      box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    }

    .title {
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #999;
      margin-bottom: 32px;
    }

    .indicator {
      width: 100px;
      height: 100px;
      border-radius: 50%;
      margin: 0 auto 24px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 40px;
    }

    .indicator.booked  { background: #fff0f0; }
    .indicator.free    { background: #f0fff4; }
    .indicator.unknown { background: #f5f5f5; }

    .status-text {
      font-size: 26px;
      font-weight: 700;
      margin-bottom: 8px;
      color: #1a1a1a;
    }

    .until-text {
      font-size: 15px;
      color: #666;
      margin-bottom: 32px;
      min-height: 22px;
    }

    .meta {
      font-size: 12px;
      color: #bbb;
      margin-bottom: 24px;
    }

    .refresh-btn {
      background: #1da462;
      color: white;
      border: none;
      border-radius: 12px;
      padding: 14px 28px;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
      width: 100%;
      transition: background 0.2s;
    }

    .refresh-btn:hover   { background: #179154; }
    .refresh-btn:active  { background: #127043; }
    .refresh-btn:disabled {
      background: #ccc;
      cursor: not-allowed;
    }

    .error-box {
      background: #fff8f0;
      border: 1px solid #ffd0a0;
      border-radius: 10px;
      padding: 12px 16px;
      font-size: 13px;
      color: #c0602a;
      margin-bottom: 20px;
      text-align: left;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="title">🅿️ Parking Space Monitor</div>

    <div class="indicator {{ indicator_class }}">{{ indicator_emoji }}</div>
    <div class="status-text">{{ status_text }}</div>
    <div class="until-text">{{ until_text }}</div>

    {% if error %}
    <div class="error-box">⚠️ {{ error }}</div>
    {% endif %}

    <div class="meta">Last checked: {{ checked_ago }}</div>

    <button class="refresh-btn" id="refreshBtn" onclick="triggerRefresh()">
      Refresh Now
    </button>
  </div>

  <script>
    function triggerRefresh() {
      const btn = document.getElementById('refreshBtn');
      btn.disabled = true;
      btn.textContent = 'Checking…';

      fetch('/refresh', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          if (data.status === 'started') {
            // Poll every 3 seconds until the check completes
            pollForResult();
          } else {
            btn.textContent = 'Already checking…';
            setTimeout(() => location.reload(), 3000);
          }
        })
        .catch(() => location.reload());
    }

    function pollForResult() {
      setTimeout(() => {
        fetch('/status')
          .then(r => r.json())
          .then(data => {
            if (data.ready) {
              location.reload();
            } else {
              pollForResult(); // keep waiting
            }
          })
          .catch(() => location.reload());
      }, 3000);
    }
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    """Serve the main status page."""
    status = read_status()

    # Decide what to show based on the current status
    if status.get("error") and status.get("active") is None:
        indicator_class = "unknown"
        indicator_emoji = "❓"
        status_text     = "Status Unknown"
        until_text      = ""
    elif status.get("active"):
        indicator_class = "booked"
        indicator_emoji = "🔴"
        status_text     = "Booking In Progress"
        until_text      = f"Until {status['until']}" if status.get("until") else ""
    else:
        indicator_class = "free"
        indicator_emoji = "🟢"
        status_text     = "No Active Booking"
        until_text      = "Space should be free"

    return render_template_string(
        PAGE_HTML,
        indicator_class = indicator_class,
        indicator_emoji = indicator_emoji,
        status_text     = status_text,
        until_text      = until_text,
        error           = status.get("error"),
        checked_ago     = format_checked_at(status.get("checked_at")),
    )


@app.route("/refresh", methods=["POST"])
def refresh():
    """Trigger a manual check in the background."""
    thread = threading.Thread(target=run_check, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/status")
def status_api():
    """
    Returns the current status as JSON.
    The page uses this to know when a refresh has completed.
    """
    status = read_status()
    # "ready" is True if the check finished within the last 20 seconds
    ready = False
    if status.get("checked_at"):
        try:
            checked = datetime.fromisoformat(status["checked_at"])
            diff    = (datetime.now() - checked).total_seconds()
            ready   = diff < 20
        except Exception:
            pass
    return jsonify({**status, "ready": ready})


def background_loop():
    """Runs forever in the background, checking every 15 minutes."""
    while True:
        run_check()
        time.sleep(15 * 60)  # Wait 15 minutes before checking again


if __name__ == "__main__":
    # Start the background loop in a separate thread
    thread = threading.Thread(target=background_loop, daemon=True)
    thread.start()
    log.info("Background checker started — will check every 15 minutes.")

    # Start the web server
    app.run(host="0.0.0.0", port=8080)
