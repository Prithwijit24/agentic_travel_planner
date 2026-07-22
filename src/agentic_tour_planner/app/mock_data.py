from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

PLACE_TEMPLATES: dict[str, list[dict]] = {
    "Kyoto": [
        {"name": "Fushimi Inari Shrine", "history": "Iconic Shinto shrine famous for its thousands of vermilion torii gates winding up Mount Inari. Founded in 711 AD.", "opening_hours": "06:00", "closing_hours": "18:00", "best_time": "Morning 06:00-08:30", "description": "A breathtaking tunnel of thousands of red gates winding through a forested mountainside.", "slot": "morning", "lat": 34.9671, "lon": 135.7727},
        {"name": "Kinkaku-ji (Golden Pavilion)", "history": "Zen Buddhist temple whose top two floors are completely covered in gold leaf. Originally built in 1397 as a shogun's retirement villa.", "opening_hours": "09:00", "closing_hours": "17:00", "best_time": "Late Morning 09:00-11:00", "description": "A stunning golden temple reflected in a serene pond surrounded by meticulously maintained gardens.", "slot": "morning", "lat": 35.0394, "lon": 135.7292},
        {"name": "Arashiyama Bamboo Grove", "history": "A natural bamboo forest with towering stalks creating an ethereal walking path. One of Kyoto's most photographed spots.", "opening_hours": "08:30", "closing_hours": "17:00", "best_time": "Early Morning 08:30-10:00", "description": "A surreal path through towering bamboo stalks that sway and creak in the wind, filtering sunlight into a green glow.", "slot": "morning", "lat": 35.0171, "lon": 135.6713},
        {"name": "Kiyomizu-dera Temple", "history": "Historic wooden temple perched on a hillside with a large veranda offering panoramic views. Founded in 778 AD and a UNESCO World Heritage site.", "opening_hours": "06:00", "closing_hours": "18:00", "best_time": "Afternoon 14:00-16:00", "description": "A massive wooden terrace built without nails, jutting out over a hillside with sweeping views of Kyoto and cherry blossoms below.", "slot": "afternoon", "lat": 34.9949, "lon": 135.7850},
        {"name": "Nishiki Market", "history": "A vibrant five-block-long covered market known as 'Kyoto's Kitchen', featuring over 100 shops and stalls selling local specialties.", "opening_hours": "09:00", "closing_hours": "18:00", "best_time": "Midday 11:00-13:00", "description": "A lively covered market with narrow lanes packed with stalls offering fresh seafood, pickles, sweets, and Kyoto specialties.", "slot": "afternoon", "lat": 35.0055, "lon": 135.7685},
        {"name": "Gion District", "history": "Kyoto's famous geisha district with preserved wooden machiya houses and teahouses where geiko and maiko entertain.", "opening_hours": "00:00", "closing_hours": "00:00", "best_time": "Evening 19:00-21:30", "description": "A historic entertainment district with cobblestone streets, traditional wooden buildings, and the chance to spot geiko in vibrant kimono.", "slot": "evening", "lat": 35.0048, "lon": 135.7750},
        {"name": "Ryoan-ji Temple", "history": "Zen temple housing Japan's most famous rock garden — 15 carefully placed stones on a bed of white gravel. Built in 1450.", "opening_hours": "08:00", "closing_hours": "17:00", "best_time": "Morning 08:00-10:00", "description": "A minimalist Zen rock garden with fifteen moss-covered stones raked into perfect white gravel, inviting quiet contemplation.", "slot": "morning", "lat": 35.0342, "lon": 135.7183},
        {"name": "Philosopher's Path", "history": "A 2km stone path along a canal lined with hundreds of cherry trees. Named after philosopher Nishida Kitaro who meditated here.", "opening_hours": "00:00", "closing_hours": "00:00", "best_time": "Afternoon 14:00-16:30", "description": "A serene stone walkway following a cherry-tree-lined canal, especially magical during cherry blossom season.", "slot": "afternoon", "lat": 35.0221, "lon": 135.7932},
        {"name": "Nijo Castle", "history": "A flatland castle built in 1603 as the Kyoto residence of the first Tokugawa Shogun. Famous for its 'nightingale floors' that chirp.", "opening_hours": "08:45", "closing_hours": "17:00", "best_time": "Morning 08:45-11:00", "description": "A magnificent castle with ornate interiors, beautiful gardens, and famously squeaky nightingale floors designed to detect intruders.", "slot": "morning", "lat": 35.0143, "lon": 135.7484},
        {"name": "Pontocho Alley", "history": "Narrow lantern-lit alley along the Kamogawa River lined with traditional eateries and teahouses dating back to the 1600s.", "opening_hours": "17:00", "closing_hours": "23:00", "best_time": "Evening 19:00-21:30", "description": "A narrow atmospheric alley with glowing lanterns, traditional restaurants on wooden decks over the river, and geisha sightings.", "slot": "evening", "lat": 35.0058, "lon": 135.7713},
    ],
}

DESTINATION_OVERVIEWS: dict[str, str] = {
    "Kyoto": "Kyoto, Japan's cultural heart, offers an unparalleled journey through centuries of tradition. From the serene bamboo groves of Arashiyama to the golden splendor of Kinkaku-ji, the city seamlessly blends ancient temples, vibrant markets, and tranquil gardens. This itinerary balances iconic landmarks with hidden gems, ensuring an immersive experience of Kyoto's timeless beauty and living culture.",
}

DESTINATION_WEATHERS: dict[str, str] = {
    "Kyoto": "October is one of Kyoto's most pleasant months with mild temperatures of 15–22°C. Expect crisp autumn air, low humidity, and the beginning of spectacular fall foliage season. Perfect for outdoor exploration.",
}

HOTEL_TEMPLATES = [
    "The Granbell Hotel — modern 4-star near Kyoto Station with rooftop bar. ~₹8,500/night",
    "Ryokan Shimizu — traditional inn with onsen and kaiseki dinner in Gion. ~₹15,000/night",
    "Hotel Gracery Kyoto — stylish 3-star in the city center. ~₹6,500/night",
    "Citadines Karasuma-Gojo Kyoto — serviced apartments with kitchenette. ~₹5,500/night",
    "The Thousand Kyoto — luxury 5-star near Kyoto Station with spa. ~₹18,000/night",
]


def _pick(count: int, items: list, offset: int = 0) -> list:
    return [items[(i + offset) % len(items)] for i in range(count)]


def _place_search_url(name: str) -> str:
    return f"https://www.google.com/maps/search/{name.replace(' ', '+')}"


def generate_mock_plan(
    destination: str,
    days: int = 4,
    interests: list[str] | None = None,
    budget: str = "midrange",
    month: str = "October",
    origin: str | None = None,
    transport_mode: str | None = "public",
    travelers: int = 1,
    places_per_day: str = "3-5",
) -> dict[str, Any]:
    interests = interests or ["temples", "food", "walks"]
    places = PLACE_TEMPLATES.get(destination, [])
    if not places:
        places = PLACE_TEMPLATES.get("Kyoto", [])

    base_budget = {"budget": 3000, "midrange": 6000, "luxury": 12000}.get(budget, 6000)

    itinerary = []
    for d in range(1, days + 1):
        offset = (d - 1) * 2
        day_places = _pick(min(3, len(places)), places, offset)
        is_last = d == days
        theme = f"Day {d} — Departure / Return Travel" if is_last else f"Day {d} — Exploring {destination}"

        spots = []
        morning_acts = []
        afternoon_acts = []
        evening_acts = []
        meals = []

        for p in day_places:
            spots.append({
                "name": p["name"],
                "slot": p["slot"],
                "history": p["history"],
                "opening_hours": p["opening_hours"],
                "closing_hours": p["closing_hours"],
                "best_time": p["best_time"],
                "description": p["description"],
            })

        if is_last:
            morning_acts = []
            afternoon_acts = []
            evening_acts = []
            meals = []
        else:
            slot_map = {"morning": morning_acts, "afternoon": afternoon_acts, "evening": evening_acts}
            for p in day_places:
                slot_map.get(p["slot"], morning_acts).append(
                    f"Visit {p['name']} ({p['best_time']}): {p['description'][:60]}"
                )
            if not morning_acts:
                morning_acts.append(f"Explore {destination} local streets and cafés (Morning 08:00-10:00)")
            if not afternoon_acts:
                afternoon_acts.append(f"Leisure walk around {destination} (Afternoon 14:00-16:00)")
            if not evening_acts:
                evening_acts.append(f"Dinner and evening stroll (Evening 19:00-21:00)")

            meals = [
                f"Breakfast at hotel — {['Japanese set', 'continental buffet', 'traditional miso soup'][d % 3]}",
                f"Lunch at {['local ramen shop near the temple', 'family-run soba restaurant', 'bento from Nishiki Market'][d % 3]}",
                f"Dinner at {['Pontocho riverside restaurant', 'izakaya in Gion', 'kaiseki ryori experience'][d % 3]}",
            ]

        weather = {
            "temperature_c": 18 + (d % 4),
            "temperature_night_c": 10 + (d % 3),
            "sunrise": f"0{5 + (d % 2)}:{['12', '45', '30'][d % 3]}",
            "sunset": f"1{7 - (d % 2)}:{['15', '30', '48'][d % 3]}",
            "humidity_percent": 55 + (d * 3),
            "rainfall_chance_percent": max(0, 30 - (d * 5)),
        }

        itinerary.append({
            "day": d,
            "theme": theme,
            "summary": f"Day {d} focuses on {', '.join(p['name'] for p in day_places[:2])}. "
                       f"{'A relaxed day exploring the cultural heart of ' + destination + '.' if not is_last else 'This is your departure day with no scheduled activities.'}",
            "transport": f"Using the efficient {transport_mode or 'public'} transport system. "
                         f"Moving between attractions via {['bus #205', 'subway Karasuma line', 'taxi (~¥1500)'][d % 3]}." if not is_last else "Transfer to airport/station.",
            "morning": morning_acts,
            "afternoon": afternoon_acts,
            "evening": evening_acts,
            "meals": meals,
            "logistics": ["Check in to hotel", "Pick up local SIM / pocket WiFi"] if d == 1 else (
                ["Check out from hotel", "Head to airport/train station"] if is_last else []
            ),
            "weather": weather,
            "spots": spots,
            "needs_hotel_change": False,
            "hotel_recommendation": HOTEL_TEMPLATES[d % len(HOTEL_TEMPLATES)] if not is_last else None,
        })

    daily_budget = base_budget * travelers
    total_budget = daily_budget * days
    cost = {
        "daily": [
            {
                "day": d,
                "items": [
                    {"label": "Hotel", "amount": "₹3,500 per room"},
                    {"label": "Food", "amount": f"₹{800 * travelers} per day"},
                    {"label": "Transport", "amount": f"₹{150 * travelers}"},
                    {"label": "Tickets", "amount": "₹500"},
                ],
                "subtotal": f"₹{3500 + 800 * travelers + 150 * travelers + 500}",
                "steps": [],
            }
            for d in range(1, days + 1)
        ],
        "overall": {
            "per_person_total": f"₹{daily_budget}",
            "members": travelers,
            "grand_total": f"₹{total_budget}",
            "steps": [],
        },
    }

    transport_options = [
        {"mode": "Bus", "description": f"City bus network covers all major attractions in {destination}", "fare": "¥230 per ride", "notes": "Day pass available for ¥600"},
        {"mode": "Subway", "description": f"Two subway lines connecting main districts in {destination}", "fare": "¥210–¥340 per ride", "notes": "IC cards accepted"},
        {"mode": "Taxi", "description": f"Taxis are readily available in central {destination}", "fare": "¥500–¥1,500 depending on distance", "notes": "Flag fall ¥500"},
    ]

    plan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    return {
        "plan_id": plan_id,
        "destination": destination,
        "days": days,
        "budget_level": budget,
        "overview": DESTINATION_OVERVIEWS.get(destination, f"A comprehensive {days}-day travel plan for {destination}."),
        "monthly_weather": DESTINATION_WEATHERS.get(destination, f"Pleasant weather expected in {month} with moderate temperatures."),
        "travel_month": month,
        "itinerary": itinerary,
        "practical_tips": [
            f"Book {destination} hotels at least 2-3 weeks in advance, especially during peak seasons.",
            f"Purchase an IC card (Suica/Pasmo) for seamless travel on {destination} public transport.",
            f"Carry cash — many smaller shops and restaurants in {destination} do not accept cards.",
            "Respect local customs: remove shoes when entering temples and traditional accommodations.",
            f"The best time for photographs in {destination} is early morning (before 9 AM) to avoid crowds.",
        ],
        "citations": [
            {"title": f"{destination} Travel Guide — Lonely Planet", "url": f"https://www.lonelyplanet.com/{destination.lower()}"},
            {"title": f"Japan National Tourism — {destination}", "url": f"https://www.japan.travel/en/destinations/{destination.lower()}/"},
            {"title": f"{destination} Official City Guide", "url": f"https://www.{destination.lower()}.travel/"},
        ],
        "generated_at": now,
        "insights": {
            "route": {
                "strategy": f"Cluster-based exploration of {destination} with efficient transit routing",
                "cluster_advice": [f"Group northern {destination} attractions together (Kinkaku-ji, Ryoan-ji)",
                                   f"Dedicate one day to eastern {destination} (Kiyomizu-dera, Gion, Yasaka)",
                                   f"Explore central {destination} (Nijo Castle, Nishiki Market, Kyoto Imperial Palace)"],
                "transit_notes": [f"Use the {destination} bus network for most attractions; subway for longer distances",
                                  f"Walking is often the best way to explore {destination}'s historic districts"],
            },
            "budget": {
                "estimated_daily_budget": float(daily_budget),
                "estimated_total_budget": float(total_budget),
                "assumptions": [f"Hotel costs estimated at ₹3,500-5,000 per night per room in {destination} budget hotels",
                                f"Food budget of ₹250-500 per meal per person at {destination} local restaurants",
                                f"Public transport day pass around ₹500 in {destination}"],
                "saving_tips": [f"Eat at local markets and convenience stores in {destination} for budget meals",
                                f"Book {destination} accommodations in shared guesthouses or hostels",
                                f"Purchase a {destination} city combo pass for discounted entry to multiple attractions"],
            },
            "timing": {
                "season_summary": f"{month} is an excellent time to visit {destination}. Mild temperatures and fewer tourists than peak season make for a comfortable experience.",
                "booking_window": f"Book flights 6-8 weeks ahead. Reserve {destination} accommodations 2-3 weeks in advance.",
                "day_planning_notes": [f"Start each day early in {destination} to beat the crowds at major temples",
                                       f"Plan for a midday break during the warmest part of the day in {destination}"],
            },
        },
        "provider_used": "mock",
        "model_used": "mock-data-v1",
        "worker_provider_used": "mock",
        "worker_model_used": "mock-data-v1",
        "transport_options": transport_options,
        "cost_estimate": cost,
        "live_web_brief": {
            "path_instructions": f"From the main train station, take bus #205 or the Karasuma subway line to reach central {destination} attractions.",
            "fair_charges": f"A meal at a mid-range {destination} restaurant costs around ¥1,000-2,000 per person.",
            "transport_availability": f"{destination} has excellent public transport with buses, subway, and taxis readily available.",
            "place_reviews": f"Top-rated {destination} attractions include Fushimi Inari Shrine (4.6★), Kinkaku-ji (4.4★), and Kiyomizu-dera (4.5★).",
            "daywise_guide": f"A typical day in {destination} starts with temple visits in the morning, market exploration midday, and cultural experiences in the evening.",
            "sources": [
                {"title": f"{destination} Official Tourism", "url": f"https://www.{destination.lower()}.travel/", "kind": "web"},
            ],
        },
        "worker_routing": {
            "route": ["mock", "mock-data-v1"],
            "budget": ["mock", "mock-data-v1"],
            "timing": ["mock", "mock-data-v1"],
        },
        "metrics": {
            "tokens": {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "failed_calls": 0},
            "time": {"total_llm_s": 0, "calls": 0, "per_provider_s": {}},
        },
    }
