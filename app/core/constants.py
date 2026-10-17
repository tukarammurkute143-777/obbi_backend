"""Business constants the chat agent answers from (never from model memory)."""

# OWNER: CONFIRM THIS LIST BEFORE GOING LIVE.
# Safar tells customers these are Obii Cabs vehicles, so it must match the real
# fleet. `seats` is the number of passengers (driver not counted) the agent will
# promise; keep it conservative. Order matters: the smallest vehicle that fits a
# group is recommended first.
VEHICLES = [
    {"name": "Swift Dzire", "aliases": ["dzire", "swift", "sedan"], "seats": 4},
    {"name": "Ertiga", "aliases": ["ertiga"], "seats": 6},
    {"name": "Innova Crysta", "aliases": ["innova", "crysta", "इनोव्हा", "इनोवा"], "seats": 7},
    {"name": "Tempo Traveller", "aliases": ["tempo", "traveller", "traveler", "टेम्पो"], "seats": 12},
]

# Obii Cabs trips to these are usually pilgrimages (used to default trip_type).
PILGRIMAGE_PLACES = {
    "Shirdi", "Shani Shingnapur", "Pandharpur", "Tuljapur", "Trimbakeshwar",
    "Nashik", "Bhimashankar", "Ganpatipule",
}
