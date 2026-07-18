#!/usr/bin/env python3
"""Log one AIS position for the boat by loading the VesselFinder embed
widget in a headless browser and reading the position data the widget
itself fetches over the network.

This is a diagnostic-first version: every response that looks relevant
(JSON content-type, or a body mentioning the vessel's MMSI) is printed
in full so we can confirm the exact shape VesselFinder returns before
locking in specific field names.
"""

import http.server
import json
import os
import socketserver
import threading
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

MMSI = "244790911"
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOG_PATH = os.path.join(REPO_ROOT, "data", "track-log.jsonl")
PORT = 8931
PAGE_WAIT_MS = 12000


def serve_repo():
    handler = http.server.SimpleHTTPRequestHandler
    os.chdir(REPO_ROOT)
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def find_lat_lon(obj):
    """Recursively search a parsed JSON value for a lat/lon-ish pair."""
    if isinstance(obj, dict):
        keys = {k.lower(): k for k in obj.keys()}
        lat_key = next((keys[k] for k in keys if k in ("lat", "latitude")), None)
        lon_key = next(
            (keys[k] for k in keys if k in ("lon", "lng", "longitude")), None
        )
        if lat_key and lon_key:
            try:
                return float(obj[lat_key]), float(obj[lon_key])
            except (TypeError, ValueError):
                pass
        for v in obj.values():
            found = find_lat_lon(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_lat_lon(item)
            if found:
                return found
    return None


def main():
    httpd = serve_repo()
    captured = []
    position = None

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        def on_response(response):
            nonlocal position
            url = response.url
            if "vesselfinder" not in url and "aismap" not in url:
                return
            content_type = response.headers.get("content-type", "")
            try:
                body = response.text()
            except Exception as exc:
                captured.append(f"{url} [{content_type}] -> could not read body: {exc}")
                return
            if "json" not in content_type and MMSI not in body:
                return
            captured.append(f"{url} [{content_type}]\n{body[:2000]}")
            if MMSI not in body:
                return
            try:
                data = json.loads(body)
            except ValueError:
                return
            found = find_lat_lon(data)
            if found and position is None:
                position = found

        page.on("response", on_response)
        page.goto(f"http://127.0.0.1:{PORT}/index.html")
        page.wait_for_timeout(PAGE_WAIT_MS)
        browser.close()

    httpd.shutdown()

    print(f"Captured {len(captured)} relevant response(s):")
    for entry in captured:
        print("----")
        print(entry)

    if position is None:
        print("Could not find a lat/lon pair for this MMSI in any captured response.")
        return

    lat, lon = position
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "lat": lat,
        "lon": lon,
    }
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"Logged position: {entry}")


if __name__ == "__main__":
    main()
