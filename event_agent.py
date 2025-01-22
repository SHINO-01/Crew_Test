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

# Securely load the API key from .env file
API_KEY = os.getenv("TICKETMASTER_API_KEY")

if not API_KEY:
    raise ValueError("API Key not found. Please set TICKETMASTER_API_KEY in your .env file.")


############################################################
# 1. Parse user input with improved preference handling
############################################################
def parse_user_input(user_input: str) -> Dict[str, str]:
    """
    Parse user input string to extract location, date, and preferences.
    This version more aggressively captures preference keywords.
    """
    # Lowercase once to simplify checks
    text_lower = user_input.lower()

    # Regex to capture location
    # Adding 'happening' in the boundary to avoid capturing it as location
    location_pattern = (
        r"(?:in|at|near)\s+([a-zA-Z\s,]+?)"
        r"(?=\s+(?:this|next|tomorrow|today|happening|\d{4}|$)|\s*$)"
    )
    # Regex to capture date references (this weekend, next weekend, 2025-01-29, etc.)
    date_pattern = (
        r"(this\s+(?:weekend|week)|next\s+(?:weekend|week)|tomorrow|today|"
        r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})"
    )

    location_match = re.search(location_pattern, text_lower)
    date_match = re.search(date_pattern, text_lower)

    # If found, extract; else None
    location = location_match.group(1).strip() if location_match else None
    parsed_date = None

    # Process date logic
    if date_match:
        date_str = date_match.group(1).strip()
        today = datetime.now()

        if date_str == "today":
            parsed_date = today.strftime("%Y-%m-%d")
        elif date_str == "tomorrow":
            parsed_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        elif "this weekend" in date_str:
            # move to the next Friday
            days_until_weekend = (5 - today.weekday()) % 7
            parsed_date = (today + timedelta(days=days_until_weekend)).strftime("%Y-%m-%d")
        elif "next weekend" in date_str:
            # move to next week's Friday
            days_until_next_weekend = (5 - today.weekday()) % 7 + 7
            parsed_date = (today + timedelta(days=days_until_next_weekend)).strftime("%Y-%m-%d")
        elif "this week" in date_str:
            parsed_date = today.strftime("%Y-%m-%d")
        elif "next week" in date_str:
            parsed_date = (today + timedelta(days=7)).strftime("%Y-%m-%d")
        else:
            # direct date formats
            try:
                if "-" in date_str:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    parsed_date = dt.strftime("%Y-%m-%d")
                elif "/" in date_str:
                    dt = datetime.strptime(date_str, "%d/%m/%Y")
                    parsed_date = dt.strftime("%Y-%m-%d")
            except ValueError:
                print(f"Warning: Could not parse date format '{date_str}'. Using None.")

    # Basic preference logic (concert, music, sports, etc.)
    # We’ll scan the entire user input for these keywords:
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

    # We default to None unless we find a matching keyword
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
# 2. Make the Ticketmaster event search more robust
############################################################
def search_events(location: str, date: str | None = None, preferences: str | None = None) -> str:
    """
    Search for events using the Ticketmaster API and return a JSON-serialized string
    that includes event images and optionally venue images (if available).
    """
    base_url = "https://app.ticketmaster.com/discovery/v2/events.json"
    
    # Basic parameters
    params = {
        'apikey': API_KEY,
        'sort': 'relevance,desc',
        'size': 10
    }

    # Distinguish if 'location' is a known country or a city
    if location and location.lower() in ["germany", "deutschland"]:
        params['countryCode'] = 'DE'
    else:
        params['city'] = location

    # If we want to interpret "next week" as exactly one day or as a date range,
    # we need to adapt here. For now, the code sets a single-day range if date is set.
    if date:
        start_datetime = f"{date}T00:00:00Z"
        end_datetime = f"{date}T23:59:59Z"
        params['startDateTime'] = start_datetime
        params['endDateTime'] = end_datetime

    # Use classification if we found a preference
    if preferences:
        params['classificationName'] = preferences

    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()  # Raise for HTTP errors (4xx/5xx)
        data = response.json()

        # If no embedded events, return an empty JSON list
        if '_embedded' not in data:
            return json.dumps([])

        events = data['_embedded'].get('events', [])
        formatted_events = []

        for event in events:
            # Grab top-level event info
            event_name = event.get('name', 'No event name')
            local_date = event['dates']['start'].get('localDate', 'TBA')
            local_time = event['dates']['start'].get('localTime', 'TBA')
            status = event['dates']['status'].get('code', 'Unknown')
            ticket_url = event.get('url', 'Not available')
            
            # Format the price range if available
            price_str = 'Price not available'
            if event.get('priceRanges'):
                pr = event['priceRanges'][0]
                currency = pr.get('currency', 'USD')
                min_price = pr.get('min', 'N/A')
                max_price = pr.get('max', 'N/A')
                price_str = f"{min_price} - {max_price} {currency}"

            # Gather event images (just the URLs). You can decide how many to include.
            event_images = []
            if 'images' in event:
                # Example: collect up to 3 image URLs
                for img in event['images'][:3]:
                    if 'url' in img:
                        event_images.append(img['url'])

            # Venue info
            venue = event['_embedded']['venues'][0]
            venue_name = venue.get('name', 'Unknown venue')
            city = venue.get('city', {}).get('name', 'N/A')
            state = venue.get('state', {}).get('name', 'N/A')

            # If the venue has images (rare in Ticketmaster, but possible), gather them similarly
            venue_images = []
            if 'images' in venue:
                # For example, just gather 1 or 2 images from the venue
                for vimg in venue['images'][:2]:
                    if 'url' in vimg:
                        venue_images.append(vimg['url'])

            formatted_event = {
                'name': event_name,
                'date': local_date,
                'time': local_time,
                'status': status,
                'ticket_url': ticket_url,
                'price_range': price_str,
                
                'venue': venue_name,
                'city': city,
                'state': state,
                
                # New fields for images
                'event_images': event_images,
                'venue_images': venue_images
            }
            formatted_events.append(formatted_event)

        # Return the serialized JSON string with optional indentation
        return json.dumps(formatted_events, indent=2)

    except requests.exceptions.RequestException as e:
        # Return an empty JSON list or an error message, depending on your needs
        print(f"Error fetching events: {str(e)}")
        return json.dumps([])



@tools.tool
def ticketmaster_event_search(location: str, date: str | None = None, preferences: str | None = None) -> List[Dict]:
    """
    Tool wrapper for searching events using Ticketmaster API.
    """
    try:
        return search_events(location, date, preferences)
    except Exception as e:
        print(f"Error in ticketmaster_event_search: {str(e)}")
        return []


############################################################
# 3. Set up the LLM and Agent
############################################################
llm = LLM(
    model="openai/gpt-4",
    temperature=0.7
)

event_planner = Agent(
    role="Event Planner",
    goal="Find and recommend the top events based on location, date, and preferences",
    backstory="""You are an experienced event planner who helps people find the best events in their area.""",
    tools=[ticketmaster_event_search],
    llm=llm,
    verbose=True
)


def create_event_search_task(location: str, date: str | None = None, preferences: str | None = None) -> Task:
    """
    Create a Task for searching events with given parameters.
    """
    description = f"""
        Find the top events in {location}
        Date: {date if date else 'Any date'}
        Preferences: {preferences if preferences else 'Any type'}
        
        1. Search for events using the Ticketmaster tool
        2. Analyze and rank them by relevance
        3. Provide a detailed summary including:
           - Event name
           - Date/time
           - Venue info
           - Price range
           - Ticket availability/status
    """

    return Task(
        description=description,
        expected_output="A list of events with relevant info, ranked by relevance.",
        agent=event_planner
    )


############################################################
# 4. Main function: fix the CrewOutput serialization issue
############################################################
def find_events(user_input: str):
    # Parse user input
    parsed = parse_user_input(user_input)
    location = parsed["location"]
    date = parsed["date"]
    preferences = parsed["preferences"]

    # Must have a location
    if not location:
        return {"error": "Location is required. Please specify a city or location."}

    # Create the search task
    task = create_event_search_task(location, date, preferences)

    # Create a Crew with the event planner
    crew = Crew(
        agents=[event_planner],
        tasks=[task],
        verbose=True
    )

    # Run the Crew
    # crew.kickoff() returns a CrewOutput object that is NOT JSON-serializable
    result = crew.kickoff()             # Returns a CrewOutput object
    return result.raw
 
    # Depending on your version of CrewAI, you might do:
    # return result.to_dict()  # if there is a to_dict() method
    # or
    # return {"output": result.final_answer}  # if final_answer is a string

    # If you just need the final text output from the agent:
    


############################################################
# 5. Running from CLI
############################################################
if __name__ == "__main__":
    print("\nWelcome to the Event Finder!")
    print("Example: 'Find music events in New York this weekend'")
    print("Example: 'Show me sports events in Los Angeles next week'")

    while True:
        try:
            user_input = input("\nWhat events are you looking for? (or 'quit' to exit): ")
            if user_input.lower() == 'quit':
                print("Thank you for using Event Finder!")
                break

            response = find_events(user_input)

            print("\nSearch Results:")
            print(json.dumps(response, indent=2))

        except Exception as e:
            print(f"An error occurred: {str(e)}")
            print("Please try again with a different query.")
