import requests
import json

def search_events(api_key, latitude, longitude, radius, start_date, end_date):
    """
    Search for events in a specific geographic location and date range using the Ticketmaster Discovery API.

    Parameters:
        api_key (str): Your Ticketmaster API key.
        latitude (float): Latitude of the specific location.
        longitude (float): Longitude of the specific location.
        radius (int): Radius in miles around the specified location.
        start_date (str): Start date in ISO8601 format (e.g., "2025-01-01T00:00:00Z").
        end_date (str): End date in ISO8601 format (e.g., "2025-01-31T23:59:59Z").

    Returns:
        list: A list of events matching the search criteria.
    """
    url = "https://app.ticketmaster.com/discovery/v2/events.json"
    params = {
        'apikey': api_key,
        'latlong': f"{latitude},{longitude}",
        'radius': radius,
        'unit': 'miles',  # Alternatively, use 'km' for kilometers
        'startDateTime': start_date,
        'endDateTime': end_date,
        'sort': 'date,asc'
    }

    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    events = data.get('_embedded', {}).get('events', [])
    return events

if __name__ == "__main__":
    API_KEY = "C80sAgdFqmgdM0Nc1q1iPvESJNSXAfSd"  # Replace with your actual Ticketmaster API key
    LATITUDE = 40.7128  # Latitude for New York City
    LONGITUDE = -74.0060  # Longitude for New York City
    RADIUS = 10  # Radius in miles
    START_DATE = "2025-01-01T00:00:00Z"
    END_DATE = "2025-01-31T23:59:59Z"

    try:
        events = search_events(API_KEY, LATITUDE, LONGITUDE, RADIUS, START_DATE, END_DATE)
        for event in events:
            print(f"Name: {event['name']}")
            print(f"Date: {event['dates']['start']['localDate']}")
            print(f"Time: {event['dates']['start'].get('localTime', 'TBA')}")
            print(f"Venue: {event['_embedded']['venues'][0]['name']}")
            print(f"URL: {event.get('url', 'Not available')}")

            # Fetch and display images
            images = event.get('images', [])
            if images:
                print("Images:")
                for image in images:
                    print(f"  - {image['url']}")
            else:
                print("Images: Not available")
            print()
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
