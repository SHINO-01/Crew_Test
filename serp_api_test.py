import http.client
import json

def search_events(api_key, query, location=None, htichips=None):
    """
    Searches for events using the HasData API via http.client.

    Parameters:
        api_key (str): Your HasData API key.
        query (str): Query string for events (e.g., "Events in New York").
        location (str): Location to search for events (e.g., "Austin, Texas, United States").
        htichips (str): Filter parameter for refining event search results. Multiple filters can be passed using commas (e.g., 'event_type:Virtual-Event,date:today').

    Returns:
        dict: A dictionary containing the search results.
    """
    conn = http.client.HTTPSConnection("api.hasdata.com")
    headers = {'x-api-key': api_key}

    # Build the request URL
    location_param = f"&location={location.replace(' ', '%20')}" if location else ""
    htichips_param = f"&htichips={htichips}" if htichips else ""
    url = f"/scrape/google/events?q={query.replace(' ', '%20')}{location_param}{htichips_param}"

    try:
        conn.request("GET", url, headers=headers)
        res = conn.getresponse()
        data = res.read()
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        print(f"Error fetching events: {e}")
        return None

# Example usage
if __name__ == "__main__":
    API_KEY = "c82731f8-e2b0-4cfb-b0ee-59b09b498be0"  # Replace with your actual API key
    QUERY = "Events in New York"
    LOCATION = "Austin, Texas, United States"
    HTICHIPS = "date:next_month"

    events = search_events(API_KEY, QUERY, LOCATION, HTICHIPS)
    if events:
        print(json.dumps(events, indent=2))
    else:
        print("No events found or an error occurred.")