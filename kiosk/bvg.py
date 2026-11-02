import pandas as pd
import datetime
import requests
from zoneinfo import ZoneInfo

berlin = ZoneInfo("Europe/Berlin")


def get_stop_data(rows, lookahead_min=30, lookback_min=5):
    """
    Returns departure data for an arbitrary list of row specs, each its own
    stop/direction/line combination (not limited to one stop with a left and
    a right direction).

    Each row spec is a dict with:
      - id: unique identifier for this row, tagged onto its matching
        departures via the "row_id" column so the caller can pick them
        back out
      - departure_id: BVG stop id to query departures from
      - direction_id: BVG stop id identifying the direction to filter for
      - line: exact line name to keep (e.g. "M245")
      - direction_text: optional, exact match against a departure's
        human-readable destination string - use this to disambiguate
        branches that share the same direction_id but end up at different
        final destinations
    """

    result = {
        "row_id": [],
        "type": [],
        "line": [],
        "departure": [],
        "delay": [],
        "direction": [],
        "cancelled": [],
    }

    when = (datetime.datetime.now(berlin) + datetime.timedelta(minutes=-lookback_min)).isoformat()
    updated_at_timestamp = None

    for row in rows:
        url = f"https://v6.bvg.transport.rest/stops/{row['departure_id']}/departures"
        params = {
            "when": when,
            "duration": lookahead_min,  # Show departures for the next selected minutes
            "remarks": True,  # Include warnings and hints
            "language": "en",  # Language of the results
            "pretty": True,  # Pretty-print JSON responses
            "direction": row["direction_id"],  # Filter departures by direction
        }

        # Send GET request with timeout
        response = requests.get(url, params=params, timeout=10)

        # Check if the request was successful
        if response.status_code == 200:
            data = response.json()  # Parse JSON response
        else:
            raise requests.HTTPError(f"Error: {response.status_code} - {response.text}")

        updated_at_timestamp = data["realtimeDataUpdatedAt"]

        for connection in data["departures"]:

            if connection["line"]["name"] != row["line"]:
                continue
            if row.get("direction_text") and connection["direction"] != row["direction_text"]:
                continue

            result["row_id"].append(row["id"])
            result["type"].append(connection["line"]["productName"])  # e.g., "Bus"
            result["line"].append(connection["line"]["name"])
            result["departure"].append(
                datetime.datetime.fromisoformat(connection["plannedWhen"]).strftime("%H:%M")
            )
            delay = 0 if connection["delay"] is None else connection["delay"]
            delay /= 60
            result["delay"].append(int(delay))  # it's not finer than minutes anyway‚
            result["direction"].append(connection["direction"])
            if "cancelled" in connection:
                result["cancelled"].append(connection["cancelled"])
            else:
                result["cancelled"].append(False)

    return updated_at_timestamp, pd.DataFrame(result)
