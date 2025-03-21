import pandas as pd
import datetime
import requests


def get_stop_data(
    departure_id="900024151", direction_id="900024104", line="M49", duration=30
):
    """
    Returns stop data for a given departure, direction, and line for the next
    selected minutes.
    """

    # API endpoint
    url = f"https://v6.bvg.transport.rest/stops/{departure_id}/departures"

    # Query parameters (customize as needed)
    params = {
        "direction": direction_id,  # Optional: Filter departures by a specific direction
        "duration": duration,  # Show departures for the next selected minutes
        "remarks": True,  # Include warnings and hints
        "language": "en",  # Language of the results
        "pretty": True,  # Pretty-print JSON responses
    }

    # Send GET request
    response = requests.get(url, params=params)

    # Check if the request was successful
    if response.status_code == 200:
        data = response.json()  # Parse JSON response
    else:
        raise requests.HTTPError(f"Error: {response.status_code} - {response.text}")

    result = {
        "type": [],
        "line": [],
        "departure": [],
        "delay": [],
        "direction": [],
        "cancelled": [],
    }

    for connection in data["departures"]:

        if connection["line"]["name"] != line:
            continue

        result["type"].append(connection["line"]["productName"])  # e.g., "Bus"
        result["line"].append(connection["line"]["name"])
        result["departure"].append(
            datetime.datetime.fromisoformat(connection["plannedWhen"]).strftime(
                "%H:%M"
            )
        )
        delay = 0 if connection["delay"] is None else connection["delay"]
        delay /= 60
        result["delay"].append(int(delay))  # it's not finer than minutes anyway‚
        result["direction"].append(connection["direction"])
        if "cancelled" in connection:
            result["cancelled"].append(connection["cancelled"])
        else:
            result["cancelled"].append(False)

    updated_at_timestamp = data["realtimeDataUpdatedAt"]

    return updated_at_timestamp, pd.DataFrame(result)
