#!/usr/bin/env python3
"""Log one AIS position report for a single vessel from aisstream.io.

Connects to the aisstream.io websocket feed, waits (up to TIMEOUT_SECONDS)
for a position report matching MMSI, and appends it as one JSON line to
the track log. If nothing arrives in time (boat out of AIS range/off),
the script exits quietly without writing anything.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import websockets

MMSI = "244790911"
STREAM_URL = "wss://stream.aisstream.io/v0/stream"
TIMEOUT_SECONDS = 90
LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "track-log.jsonl")


async def fetch_position():
    api_key = os.environ.get("AISSTREAM_API_KEY")
    if not api_key:
        print("AISSTREAM_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    subscribe_message = {
        "APIKey": api_key,
        "BoundingBoxes": [[[-90, -180], [90, 180]]],
        "FiltersShipMMSI": [MMSI],
        "FilterMessageTypes": ["PositionReport"],
    }

    async with websockets.connect(STREAM_URL) as ws:
        await ws.send(json.dumps(subscribe_message))
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                async for raw in ws:
                    data = json.loads(raw)
                    if data.get("MessageType") != "PositionReport":
                        continue
                    meta = data.get("MetaData", {})
                    if str(meta.get("MMSI")) != MMSI:
                        continue
                    report = data.get("Message", {}).get("PositionReport", {})
                    return {
                        "time": meta.get("time_utc")
                        or datetime.now(timezone.utc).isoformat(),
                        "lat": meta.get("latitude", report.get("Latitude")),
                        "lon": meta.get("longitude", report.get("Longitude")),
                        "sog": report.get("Sog"),
                        "cog": report.get("Cog"),
                        "heading": report.get("TrueHeading"),
                    }
        except TimeoutError:
            return None


def append_to_log(entry):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def main():
    entry = asyncio.run(fetch_position())
    if entry is None:
        print(f"No position for MMSI {MMSI} within {TIMEOUT_SECONDS}s, skipping.")
        return
    append_to_log(entry)
    print(f"Logged position: {entry}")


if __name__ == "__main__":
    main()
