import os
import re
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta
from crewai import LLM, Agent, Task, Crew, tools
import warnings
import requests
from typing import Dict, List

warnings.filterwarnings('ignore')

# Load environment variables
load_dotenv()

API_KEY = os.getenv("TICKETMASTER_API_KEY")
if not API_KEY:
    raise ValueError("API Key not found. Please set TICKETMASTER_API_KEY in your .env file.")

############################################################
# 1. Parse user input
############################################################
def parse_user_input(user_input: str) -> Dict[str, str]:
    text_lower = user_input.lower()

    # Capture location
    location_pattern = (
        r"(?:in|at|near)\s+([a-zA-Z\s,]+?)"
        r"(?=\s+(?:this|next|tomorrow|today|happening|\d{4}|$)|\s*$)"
    )
    location_match = re.search(location_pattern, text_lower)
    location = location_match.group(1).strip() if location_match else None

    # Capture date references
    date_pattern = (
        r"(this\s+(?:weekend|week)|next\s+(?:weekend|week)|tomorrow|today|"
        r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})"
    )
    date_match = re.search(date_pattern, text_lower)
    parsed_date = None
    if date_match:
        date_str = date_match.group(1).strip()
        today = datetime.now()
        if date_str == "today":
            parsed_date = today.strftime("%Y-%m-%d")
        elif date_str == "tomorrow":
            parsed_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        elif "this weekend" in date_str:
            days_until_weekend = (5 - today.weekday()) % 7
            parsed_date = (today + timedelta(days=days_until_weekend)).strftime("%Y-%m-%d")
        elif "next weekend" in date_str:
            days_until_next_weekend = (5 - today.weekday()) % 7 + 7
            parsed_date = (today + timedelta(days=days_until_next_weekend)).strftime("%Y-%m-%d")
        elif "this week" in date_str:
            parsed_date = today.strftime("%Y-%m-%d")
        elif "next week" in date_str:
            parsed_date = (today + timedelta(days=7)).strftime("%Y-%m-%d")
        else:
            try:
                if "-" in date_str:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    parsed_date = dt.strftime("%Y-%m-%d")
                elif "/" in date_str:
                    dt = datetime.strptime(date_str, "%d/%m/%Y")
                    parsed_date = dt.strftime("%Y-%m-%d")
            except ValueError:
                print(f"Warning: Could not parse date '{date_str}'.")

    # Preferences
    preference_keywords = {
        "music": "Music",
        "concert": "Music",
        "concerts": "Music",
        "sports": "Sports",
        "theater": "Arts & Theatre",
        "theatre": "Arts & Theatre",
        "family": "Family",
        "comedy": "Arts & Theatre",
        "musical": "Arts & Theatre",
        "dance": "Arts & Theatre"
    }
    found_preference = None
    for keyword, category in preference_keywords.items():
        if keyword in text_lower:
            found_preference = category
            break

    return {
        "location": location,
        "date": parsed_date,
        "preferences": found_preference
    }

############################################################
# 2. Weather Tool (Agent calls this)
############################################################
@tools.tool
def open_meteo_weather(latitude: float, longitude: float, date: str) -> str:
    """
    Query the Open-Meteo API for a single day forecast.
    Returns a JSON string with max/min temps, precipitation, etc.
    The agent calls this tool as needed.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return json.dumps({"error": "Invalid date format or TBA."})

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum,snowfall_sum",
        "start_date": date,
        "end_date": date,
        "timezone": "auto"
    }

    try:
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if "daily" not in data:
            return json.dumps({"error": "No daily weather data."})

        daily = data["daily"]
        weather_info = {
            "date": date,
            "temperature_2m_max": daily["temperature_2m_max"][0] if daily["temperature_2m_max"] else None,
            "temperature_2m_min": daily["temperature_2m_min"][0] if daily["temperature_2m_min"] else None,
            "precipitation_sum": daily["precipitation_sum"][0] if daily["precipitation_sum"] else None,
            "rain_sum": daily["rain_sum"][0] if daily["rain_sum"] else None,
            "snowfall_sum": daily["snowfall_sum"][0] if daily["snowfall_sum"] else None
        }
        return json.dumps(weather_info)
    except requests.exceptions.RequestException as e:
        return json.dumps({"error": str(e)})

############################################################
# 3. Ticketmaster Event Search
############################################################
def search_events(location: str, date: str | None = None, preferences: str | None = None) -> str:
    """
    Search for events using Ticketmaster API and return JSON string.
    This function does NOT call the weather tool. The agent will handle weather calls.
    """
    base_url = "https://app.ticketmaster.com/discovery/v2/events.json"

    params = {
        'apikey': API_KEY,
        'sort': 'relevance,desc',
        'size': 10
    }

    if location and location.lower() in ["germany", "deutschland"]:
        params['countryCode'] = 'DE'
    else:
        params['city'] = location

    if date:
        start_datetime = f"{date}T00:00:00Z"
        end_datetime = f"{date}T23:59:59Z"
        params['startDateTime'] = start_datetime
        params['endDateTime'] = end_datetime

    if preferences:
        params['classificationName'] = preferences

    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()

        if '_embedded' not in data:
            return json.dumps([])

        events = data['_embedded'].get('events', [])
        formatted_events = []

        for event in events:
            event_name = event.get('name', 'No event name')
            local_date = event['dates']['start'].get('localDate', 'TBA')
            local_time = event['dates']['start'].get('localTime', 'TBA')
            status = event['dates']['status'].get('code', 'Unknown')
            ticket_url = event.get('url', 'Not available')
            event_description = event.get('description', 'No event description')
            price_str = 'Price not available'
            if event.get('priceRanges'):
                pr = event['priceRanges'][0]
                currency = pr.get('currency', 'USD')
                min_price = pr.get('min', 'N/A')
                max_price = pr.get('max', 'N/A')
                price_str = f"{min_price} - {max_price} {currency}"

            venue = event['_embedded']['venues'][0]
            venue_name = venue.get('name', 'Unknown venue')
            city = venue.get('city', {}).get('name', 'N/A')
            state = venue.get('state', {}).get('name', 'N/A')
            lat = venue.get('location', {}).get('latitude', None)
            lng = venue.get('location', {}).get('longitude', None)

            formatted_event = {
                "name": event_name,
                "date": local_date,
                "time": local_time,
                "description": event_description,
                "status": status,
                "ticket_url": ticket_url,
                "price_range": price_str,
                "venue": venue_name,
                "city": city,
                "state": state,
                "latitude": lat,
                "longitude": lng
            }

            formatted_events.append(formatted_event)

        return json.dumps(formatted_events, indent=2)

    except requests.exceptions.RequestException as e:
        print(f"Error fetching events: {str(e)}")
        return json.dumps([])

@tools.tool
def ticketmaster_event_search(location: str, date: str | None = None, preferences: str | None = None) -> str:
    """
    CrewAI tool that just calls the Ticketmaster API (no weather).
    """
    try:
        return search_events(location, date, preferences)
    except Exception as e:
        print(f"Error in ticketmaster_event_search: {str(e)}")
        return json.dumps([])

############################################################
# 4. Agent Setup (Enhanced)
############################################################
llm = LLM(
    model="openai/gpt-4",
    temperature=0.7
)

event_planner = Agent(
    role="Event Planner",
    goal="Retrieve events, fetch weather data for each event, and make 2 final suggestions along with their reasons.",
    backstory=(
        "You are an event planner. For each user query, you:\n"
        "1) Use 'ticketmaster_event_search' to fetch events.\n"
        "2) For each event's date/lat/long, call 'open_meteo_weather' if date is not TBA.\n"
        "3) Return ALL events and their weather data.\n"
        "4) Then suggest TWO events to attend, based on weather and event type.\n"
        "Don't summarize just one or two events. Return them all, then pick your top 2 and state your reason in short.\n"
    ),
    tools=[ticketmaster_event_search, open_meteo_weather],
    llm=llm,
    verbose=True
)

def create_event_search_task(location: str, date: str | None = None, preferences: str | None = None) -> Task:
    description = f"""
        The user wants events in {location} on {date if date else 'any date'} 
        with preferences {preferences if preferences else 'any type'}.
        Step-by-step:
        1. Call 'ticketmaster_event_search' to get up to 10 events.
        2. For each event, if 'date' is not TBA, call 'open_meteo_weather' 
           with the event's latitude, longitude, and date.
        3. Output ALL events with integrated weather info.
        4. Finally, based on the forecast and event type, provide TWO recommended events 
           for the user. 
        5. Format your final answer with all events, then the 2 suggestions.
    """

    return Task(
        description=description,
        expected_output=(
            "All events with weather, plus a final 'Suggestions' section listing two recommended events."
        ),
        agent=event_planner
    )

############################################################
# 5. Main find_events + CLI
############################################################
def find_events(user_input: str):
    """
    1. Parse user input
    2. Create a Task instructing the agent to:
       - get all events
       - fetch weather
       - provide 2 final suggestions
    3. Return the final agent output
    """
    inputs = parse_user_input(user_input)
    location = inputs["location"]
    date = inputs["date"]
    preferences = inputs["preferences"]
    if not location:
        return {"error": "Location is required. Please specify a city or location."}

    task = create_event_search_task(location, date, preferences)
    crew = Crew(agents=[event_planner], tasks=[task], verbose=True)
    result = crew.kickoff()  # returns a CrewOutput
    return result.raw  # typically a string


if __name__ == "__main__":
    print("\nWelcome to the Enhanced Event Finder!")
    print("Try something like: 'Find music events in New York tomorrow'")

    while True:
        try:
            user_input = input("\nWhat events are you looking for? (or 'quit' to exit): ")
            if user_input.lower() == 'quit':
                print("Thank you for using Event Finder!")
                break

            response = find_events(user_input)
            if isinstance(response, str):
                try:
                    # Attempt to parse if it's valid JSON
                    parsed = json.loads(response)
                    print("\nSearch Results (parsed JSON):")
                    print(json.dumps(parsed, indent=2))
                except json.JSONDecodeError:
                    # Not valid JSON, print raw text
                    print("\nSearch Results (raw text):")
                    print(response)
            else:
                # If it's already a dict, just pretty-print
                print("\nSearch Results (dict):")
                print(json.dumps(response, indent=2))

        except Exception as e:
            print(f"An error occurred: {str(e)}")
            print("Please try again.")
