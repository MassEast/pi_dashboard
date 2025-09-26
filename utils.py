import pandas as pd
import datetime
import requests
from zoneinfo import ZoneInfo

berlin = ZoneInfo("Europe/Berlin")


def get_stop_data(
    departure_id="900024151",
    direction_id_left="900024104",
    direction_id_right="900024106",
    line="M49",
    lookahead_min=30,
    lookback_min=5,
):
    """
    Returns stop data for a given departure, left and right directions, and
    line for the next selected minutes.
    """

    # API endpoint
    url = f"https://v6.bvg.transport.rest/stops/{departure_id}/departures"

    # Query parameters (customize as needed)
    params = {
        "when": (
            datetime.datetime.now(berlin) + datetime.timedelta(minutes=-lookback_min)
        ).isoformat(),
        "duration": lookahead_min,  # Show departures for the next selected minutes
        "remarks": True,  # Include warnings and hints
        "language": "en",  # Language of the results
        "pretty": True,  # Pretty-print JSON responses
    }

    result = {
        "type": [],
        "line": [],
        "departure": [],
        "delay": [],
        "direction": [],
        "direction_str": [],
        "cancelled": [],
    }

    for direction_str, direction_id in zip(
        ["left", "right"], [direction_id_left, direction_id_right]
    ):
        if direction_id is None:
            continue
        params["direction"] = direction_id  # Optional: Filter departures by a specific direction

        # Send GET request with timeout
        response = requests.get(url, params=params, timeout=10)

        # Check if the request was successful
        if response.status_code == 200:
            data = response.json()  # Parse JSON response
        else:
            raise requests.HTTPError(f"Error: {response.status_code} - {response.text}")

        for connection in data["departures"]:

            if connection["line"]["name"] != line:
                continue

            result["type"].append(connection["line"]["productName"])  # e.g., "Bus"
            result["line"].append(connection["line"]["name"])
            result["departure"].append(
                datetime.datetime.fromisoformat(connection["plannedWhen"]).strftime("%H:%M")
            )
            delay = 0 if connection["delay"] is None else connection["delay"]
            delay /= 60
            result["delay"].append(int(delay))  # it's not finer than minutes anyway‚
            result["direction"].append(connection["direction"])
            result["direction_str"].append(direction_str)
            if "cancelled" in connection:
                result["cancelled"].append(connection["cancelled"])
            else:
                result["cancelled"].append(False)

    updated_at_timestamp = data["realtimeDataUpdatedAt"]

    return updated_at_timestamp, pd.DataFrame(result)
