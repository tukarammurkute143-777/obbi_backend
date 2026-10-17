"""Business constants the chat agent answers from (never from model memory)."""

# The Obii Cabs fleet, as listed on the website (frontend src/lib/fleet/constants.ts).
# `seats` is the number of passengers the agent will promise; keep it in step
# with the website. Smallest first: the first vehicle that fits a group is the
# one recommended.
VEHICLES = [
    {"name": "Swift Dzire", "aliases": ["dzire", "swift", "sedan"], "seats": 4},
    {"name": "Maruti Ertiga", "aliases": ["ertiga"], "seats": 6},
    {"name": "Innova Crysta", "aliases": ["innova", "crysta", "इनोव्हा", "इनोवा"], "seats": 7},
    {"name": "Kia Carens", "aliases": ["carens", "kia"], "seats": 7},
    {"name": "Force Urbania", "aliases": ["urbania", "tempo", "traveller", "traveler", "अर्बानिया"], "seats": 17},
    {"name": "Mini Bus", "aliases": ["mini bus", "minibus"], "seats": 26},
    {"name": "Full Bus", "aliases": ["full bus", "bus"], "seats": 50},
]

# Obii Cabs trips to these are usually pilgrimages (used to default trip_type).
PILGRIMAGE_PLACES = {
    "Shirdi", "Shani Shingnapur", "Pandharpur", "Tuljapur", "Trimbakeshwar",
    "Nashik", "Bhimashankar", "Ganpatipule",
}
