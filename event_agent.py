import os
import re
import json
from dotenv import load_dotenv
from datetime import datetime
from crewai import LLM, Agent, Task, Crew
import warnings
from ticket_master_api import search_events  # Importing the Ticketmaster API

warnings.filterwarnings('ignore')

# Load environment variables
load_dotenv()

# Securely load the API key from .env file
API_KEY = os.getenv("TICKETMASTER_API_KEY")

if not API_KEY:
    raise ValueError("API Key not found. Please set TICKETMASTER_API_KEY in your .env file.")

# Initialize LLM
llm = LLM(
    model="openai/gpt-4",
    temperature=0.7
)

# Define agents
planner = Agent(
    role="Event Planner",
    goal="Identify events based on location, date, preferences, and specific event names or programs.",
    backstory="You're tasked with finding events in the user's area "
              "that match their preferences, timing, and optionally a specific event or program.",
    allow_delegation=False,
    llm=llm,
    verbose=True
)

# Define tasks
event_task = Task(
    description=(
        "Find events based on the following inputs:\n"
        "- Location: {location}\n"
        "- Date: {date}\n"
        "- Preferences: {preferences}\n"
        "- Event Name: {event_name}\n"
        "Return a list of events matching these inputs."
    ),
    expected_output="A list of events with details (name, location, date, type, relevance to user input).",
    agent=planner
)

crew = Crew(
    agents=[planner],
    tasks=[event_task],
    verbose=True
)

# Function to parse user input
def parse_user_input(user_input):
    location_pattern = r"in\s([a-zA-Z\s]+)"
    date_pattern = r"(this weekend|tomorrow|next week|today|\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})"
    preferences_pattern = r"(outdoor|indoor|family-friendly|music|sports|adventure)"
    event_name_pattern = r"about\s([a-zA-Z\s]+)"

    location_match = re.search(location_pattern, user_input)
    location = location_match.group(1).strip() if location_match else None

    date_match = re.search(date_pattern, user_input)
    date_raw = date_match.group(0).strip() if date_match else None
    date = None
    if date_raw:
        try:
            if "-" in date_raw or "/" in date_raw:
                date = datetime.strptime(date_raw, "%Y-%m-%d").strftime("%Y-%m-%d") if "-" in date_raw else datetime.strptime(date_raw, "%d/%m/%Y").strftime("%Y-%m-%d")
            else:
                date = date_raw
        except ValueError:
            print(f"Error: Invalid date format '{date_raw}'. Please use YYYY-MM-DD or DD/MM/YYYY.")

    preferences_matches = re.findall(preferences_pattern, user_input)
    preferences = ", ".join(preferences_matches) if preferences_matches else None

    event_name_match = re.search(event_name_pattern, user_input)
    event_name = event_name_match.group(1).strip() if event_name_match else None

    return {
        "location": location,
        "date": date,
        "preferences": preferences,
        "event_name": event_name
    }

# Function to fetch events using Ticketmaster API
def fetch_events(location, date, preferences, event_name):
    # Dummy latitude and longitude for simplicity (convert location to coordinates in a real implementation)
    latitude = 40.7128  # Replace with geocoding results
    longitude = -74.0060
    radius = 10  # Default radius in miles

    # Parse start and end dates from the input date (for simplicity, using the same date for start and end)
    if date:
        start_date = f"{date}T00:00:00Z"
        end_date = f"{date}T23:59:59Z"
    else:
        start_date = "2025-01-01T00:00:00Z"
        end_date = "2025-01-31T23:59:59Z"

    try:
        events = search_events(API_KEY, latitude, longitude, radius, start_date, end_date)
        return events
    except Exception as e:
        return {"error": str(e)}

# Get user input
user_input = input("Tell me what you're looking for (e.g., 'I want to find outdoor family-friendly events in New York on 2025-02-15 about music festivals'): ")

# Parse user input
inputs = parse_user_input(user_input)

# Ensure location is provided
if not inputs["location"]:
    print("Error: Location is required. Please specify a location (e.g., 'in New York').")
else:
    # Set default values for optional fields
    inputs["date"] = inputs["date"] or "2025-01-01"
    inputs["preferences"] = inputs["preferences"] or "any"
    inputs["event_name"] = inputs["event_name"] or "general events"

    # Fetch events
    events = fetch_events(inputs["location"], inputs["date"], inputs["preferences"], inputs["event_name"])
    print("Fetched Events:")
    print(json.dumps(events, indent=4))
