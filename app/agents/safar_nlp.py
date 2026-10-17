"""
Language, intent and entity detection for Safar. Pure functions, no I/O.

Everything here is rule based on purpose. The two things that must never go
wrong - sending a price or booking question to the phone, and recognising that a
booking is confirmed - cannot depend on a model's mood, and rules run in
microseconds.

Design rules:
  * Pricing wins ties. When a message is ambiguous between a price question and
    anything else, it is treated as a price question (a redirect to the phone is
    always a safe answer).
  * "booking confirmed" needs an unambiguous statement: no question, no
    negation. "booking nahi hui" and "is my booking confirmed?" do not count.
  * Devanagari is matched on whole tokens or fixed phrases, never on substrings
    of words (Marathi/Hindi "दर" must not match inside "सुंदर").
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from app.core.constants import VEHICLES

_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_DEV = re.compile(r"[ऀ-ॿ]")
_TOKEN = re.compile(r"[a-z]+|[ऀ-ॿ]+|\d+")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").translate(_DIGITS).lower()
    return re.sub(r"\s+", " ", t).strip()


def tokens(norm: str) -> list[str]:
    return _TOKEN.findall(norm)


def has_devanagari(text: str) -> bool:
    return bool(_DEV.search(text or ""))


def _roman(*phrases: str) -> re.Pattern:
    """Whole-word match for any of the phrases (spaces inside phrases allowed)."""
    body = "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in phrases)
    return re.compile(rf"(?<![a-z0-9])(?:{body})(?![a-z0-9])")


# ------------------------------------------------------------------ language

_MR_ROMAN = {"kiti", "aahe", "ahe", "aahet", "aahes", "mala", "tumhi", "tumhala", "kay", "kasa",
             "kashi", "kuthe", "pahije", "pahijet", "zali", "zala", "jhali", "jhala", "karaycha",
             "karaychi", "karayche", "hoil", "aamhi", "amhi", "tumcha", "tumchi", "mhanje",
             "madhe", "pasun", "lagel", "padel", "kela", "kele", "nako", "ani", "sangaa", "sanga",
             "kitihi", "lagto", "dakhva", "dya", "dyaa", "tumchyasathi", "aapan"}
_HI_ROMAN = {"kitna", "kitne", "kitni", "hai", "hain", "kya", "aap", "mujhe", "chahiye", "karna",
             "karein", "karo", "batao", "bataiye", "batayiye", "nahi", "nahin", "mein", "hum",
             "hoga", "lagega", "gaya", "gayi", "liya", "kahan", "kaise", "kab", "bhi", "aur", "ho",
             "kar", "hu", "hoon", "tak", "ko", "main", "mai", "se", "ka", "ki", "ke", "wahan",
             "yahan", "jana", "jaana", "chalega", "dur", "door", "gaadi", "gadi", "haan", "acha",
             "achha", "theek", "bataoge", "banao", "karu", "karunga", "namaste", "namaskar", "pranam"}
_EN_WORDS = {"the", "is", "are", "what", "how", "which", "from", "to", "please", "can", "you", "me",
             "my", "for", "with", "distance", "trip", "book", "booking", "plan", "hotel", "far",
             "long", "time", "best", "places", "visit", "i", "we", "need", "want", "tell", "about",
             "and", "in", "of", "hello", "hi", "thanks", "thank", "days", "day", "people", "cab",
             "car", "route", "weather", "where", "stay", "when", "do", "does", "will", "would",
             "could", "there", "any", "some", "a", "an", "it", "this", "that", "yes", "no", "ok"}
_MR_DEV = {"आहे", "आहेत", "आहात", "मी", "तुम्ही", "तुमचा", "तुमची", "तुमचे", "काय", "किती", "झाली",
           "झालं", "झाले", "करा", "आम्ही", "होईल", "पाहिजे", "हवे", "हवी", "हवा", "साठी", "मध्ये",
           "पासून", "कुठे", "कसे", "कसा", "सांगा", "मला", "आपण", "ते", "पर्यंत", "आणि", "नाही",
           "लागेल", "द्या", "बुक", "केली", "केले", "केलं", "माझी", "माझे", "जायचे", "जायचं", "नको",
           "तर", "ला", "ची", "चा", "चे"}
_HI_DEV = {"है", "हैं", "मैं", "आप", "क्या", "कितना", "कितने", "कितनी", "नहीं", "करें", "कहाँ",
           "कहां", "चाहिए", "मुझे", "हम", "के", "की", "को", "में", "से", "बताइए", "बताओ", "बताएं",
           "कैसे", "कब", "और", "भी", "था", "थी", "हूँ", "हूं", "गया", "गई", "गयी", "लिया", "तक",
           "करो", "करना", "जाना", "जाने", "वहाँ", "यहाँ", "का", "हो", "कर"}


def detect_language(text: str, previous: Optional[str] = None) -> tuple[str, bool]:
    """
    (language, confident). language is english | hindi | marathi | hinglish.
    Not confident means the message gave no signal (just names or numbers), so
    the caller should keep the session's language.
    """
    norm = normalize(text)
    toks = tokens(norm)
    if has_devanagari(norm):
        dev = [t for t in toks if _DEV.match(t)]
        mr = sum(t in _MR_DEV for t in dev)
        hi = sum(t in _HI_DEV for t in dev)
        if mr > hi:
            return "marathi", True
        if hi > mr:
            return "hindi", True
        return (previous if previous in ("hindi", "marathi") else "hindi"), False

    rom = [t for t in toks if t.isalpha()]
    mr = sum(t in _MR_ROMAN for t in rom)
    hi = sum(t in _HI_ROMAN for t in rom)
    en = sum(t in _EN_WORDS for t in rom)
    if mr > hi and mr >= 1:
        return "marathi", True
    if hi >= 1:
        # "to" and "hi" are shared with English/Hindi; real mixing needs 2+ English words.
        return ("hinglish" if en >= 2 and en >= hi else "hindi"), True
    if en >= 1:
        return "english", True
    return (previous or "english"), False


def reply_language_key(language: str, message: str) -> str:
    """Template set to use: en | hi (Roman Hindi/Hinglish) | hi_dev | mr."""
    if language == "marathi":
        return "mr"
    if language in ("hindi", "hinglish"):
        return "hi_dev" if has_devanagari(message) else "hi"
    return "en"


# -------------------------------------------------------------------- places

# canonical name -> aliases. Roman aliases match whole words; Devanagari aliases
# match as prefixes of a word so Marathi suffixes (पुण्याला, शिर्डीहून) still hit.
PLACES: dict[str, list[str]] = {
    "Pune": ["pune", "poona", "पुणे", "पुण्या"],
    "Shirdi": ["shirdi", "shridi", "shiridi", "sirdi", "शिर्डी", "शिरडी", "शिर्डि"],
    "Mumbai": ["mumbai", "bombay", "मुंबई", "मुम्बई"],
    "Nashik": ["nashik", "nasik", "नाशिक", "नासिक"],
    "Aurangabad": ["aurangabad", "sambhajinagar", "chhatrapati sambhajinagar", "औरंगाबाद",
                   "संभाजीनगर"],
    "Lonavala": ["lonavala", "lonavla", "khandala", "लोणावळा", "लोणावळ्या", "लोनावला"],
    "Mahabaleshwar": ["mahabaleshwar", "mahabaleswar", "महाबळेश्वर", "महाबलेश्वर"],
    "Panchgani": ["panchgani", "पाचगणी"],
    "Kolhapur": ["kolhapur", "कोल्हापूर", "कोल्हापुर"],
    "Nagpur": ["nagpur", "नागपूर", "नागपुर"],
    "Pandharpur": ["pandharpur", "पंढरपूर", "पंढरपुर"],
    "Tuljapur": ["tuljapur", "तुळजापूर", "तुलजापुर"],
    "Trimbakeshwar": ["trimbakeshwar", "trimbak", "त्र्यंबकेश्वर", "त्र्यम्बकेश्वर"],
    "Shani Shingnapur": ["shani shingnapur", "shingnapur", "शनि शिंगणापूर", "शिंगणापूर"],
    "Alibag": ["alibag", "alibaug", "अलिबाग"],
    "Ganpatipule": ["ganpatipule", "गणपतीपुळे"],
    "Matheran": ["matheran", "माथेरान"],
    "Satara": ["satara", "सातारा"],
    "Solapur": ["solapur", "सोलापूर", "सोलापुर"],
    "Bhimashankar": ["bhimashankar", "भीमाशंकर"],
    "Ellora": ["ellora", "ajanta", "वेरूळ", "एलोरा", "अजिंठा"],
    "Goa": ["goa", "गोवा", "गोआ"],
    "Ratnagiri": ["ratnagiri", "रत्नागिरी"],
    "Nanded": ["nanded", "नांदेड", "नांदेड़"],
    "Sangli": ["sangli", "सांगली"],
    "Ahilyanagar": ["ahilyanagar", "ahmednagar", "अहमदनगर", "अहिल्यानगर"],
    "Hyderabad": ["hyderabad", "हैदराबाद", "हैदराबाद"],
    "Bengaluru": ["bengaluru", "bangalore", "बेंगळुरू", "बंगळूर", "बेंगलुरु"],
    "Indore": ["indore", "इंदौर", "इंदूर"],
    "Ahmedabad": ["ahmedabad", "अहमदाबाद"],
    "Surat": ["surat", "सुरत"],
}
_ROMAN_PLACE = {}
_DEV_PLACE = {}
for _canon, _aliases in PLACES.items():
    for _a in _aliases:
        (_DEV_PLACE if _DEV.search(_a) else _ROMAN_PLACE)[_a] = _canon
_ROMAN_PLACE_RE = re.compile(
    r"(?<![a-z0-9])(" + "|".join(sorted(map(re.escape, _ROMAN_PLACE), key=len, reverse=True))
    + r")(?![a-z0-9])")
_DEV_PLACE_RE = re.compile("(" + "|".join(sorted(map(re.escape, _DEV_PLACE), key=len, reverse=True)) + ")")
_FROM_AFTER = re.compile(r"^(?:[ऀ-ॿ]{0,3}(?:हून|पासून|से|ते)|\s*(?:se|से|ते|pasun|hun|ke paas se)(?![a-z]))")
_TITLE_PAIR = re.compile(
    r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s+(?:se|to)\s+([A-Z][a-z]+(?: [A-Z][a-z]+)?)\b")


_AFTER_SE = re.compile(r"\b(?:se|to)\s+([A-Z][a-z]{2,}(?:\s[A-Z][a-z]+)?)")
_BEFORE_SE = re.compile(r"\b([A-Z][a-z]{2,}(?:\s[A-Z][a-z]+)?)\s+(?:se|to)\s")


@dataclass
class Places:
    from_city: Optional[str] = None
    to_city: Optional[str] = None
    found: list = field(default_factory=list)


def extract_places(raw: str) -> Places:
    """Cities named in the message. 'X se Y' / 'X to Y' / 'X ते Y' give from and to;
    a place followed by se/पासून/हून is the origin, a lone other place is the destination."""
    norm = normalize(raw)
    hits: list[tuple[int, int, str]] = []
    for rx in (_ROMAN_PLACE_RE, _DEV_PLACE_RE):
        for m in rx.finditer(norm):
            canon = _ROMAN_PLACE.get(m.group(1)) or _DEV_PLACE.get(m.group(1))
            hits.append((m.start(), m.end(), canon))
    hits.sort()

    ordered: list[tuple[str, bool]] = []   # (canonical, followed by a from-marker)
    for start, end, canon in hits:
        if any(c == canon for c, _ in ordered):
            continue
        ordered.append((canon, bool(_FROM_AFTER.match(norm[end:end + 14]))))

    out = Places(found=[c for c, _ in ordered])
    if len(ordered) >= 2:
        origin = next((c for c, f in ordered if f), None)
        if origin:
            out.from_city = origin
            out.to_city = next(c for c, _ in ordered if c != origin)
        else:
            out.from_city, out.to_city = ordered[0][0], ordered[1][0]
    elif len(ordered) == 1:
        canon, is_from = ordered[0]
        if is_from:
            out.from_city = canon
        else:
            out.to_city = canon

    if not out.found:   # unknown cities: only trust clearly capitalised "A to B" / "A se B"
        m = _TITLE_PAIR.search(raw or "")
        if m:
            out.from_city, out.to_city = m.group(1), m.group(2)
            out.found = [out.from_city, out.to_city]
    elif out.from_city and not out.to_city:   # "Pune se Karad": the other end is unknown to us
        m = _AFTER_SE.search(raw or "")
        if m and m.group(1).lower() not in _ROMAN_PLACE:
            out.to_city = m.group(1)
            out.found.append(out.to_city)
    elif out.to_city and not out.from_city:
        m = _BEFORE_SE.search(raw or "")
        if m and m.group(1).lower() not in _ROMAN_PLACE and m.group(1) != out.to_city:
            out.from_city = m.group(1)
            out.found.append(out.from_city)
    return out


# ------------------------------------------------------------ number entities

_WORD_NUM = {"ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4,
             "four": 4, "paanch": 5, "panch": 5, "five": 5, "chhe": 6, "che": 6, "six": 6,
             "saat": 7, "seven": 7, "aath": 8, "eight": 8, "nau": 9, "nine": 9, "das": 10,
             "ten": 10, "एक": 1, "दोन": 2, "दो": 2, "तीन": 3, "चार": 4, "पाच": 5, "पांच": 5,
             "पाँच": 5, "सहा": 6, "छह": 6, "सात": 7, "आठ": 8, "नऊ": 9, "नौ": 9, "दहा": 10, "दस": 10}
_NUM = r"(\d{1,3}|" + "|".join(sorted(map(re.escape, _WORD_NUM), key=len, reverse=True)) + r")"
_DAYS_RE = re.compile(
    rf"(?<![a-z0-9]){_NUM}\s*(?:din|dino|days?|day|raat|raatri|night|nights|दिन|दिवस|दिवसांची|रात)")
_PEOPLE_RE = re.compile(
    rf"(?<![a-z0-9]){_NUM}\s*(?:log|logo|lok|people|persons?|members?|adults?|passengers?|pax|"
    r"jan|janaan|लोग|लोक|जण|माणसे|व्यक्ती|सदस्य|सदस्यों)")
_PEOPLE_RE2 = re.compile(
    rf"(?:we are|we r|hum|aamhi|amhi|आम्ही|हम)\s+{_NUM}(?![a-z0-9]*\s*(?:din|day))")
_ONLY_NUMBER = re.compile(rf"^\s*{_NUM}\s*[.!]?\s*$")


def _num(token: str) -> Optional[int]:
    if token.isdigit():
        return int(token)
    return _WORD_NUM.get(token)


def extract_days(norm: str, awaiting: bool = False) -> Optional[int]:
    m = _DAYS_RE.search(norm)
    if m:
        return _num(m.group(1))
    if awaiting:
        m = _ONLY_NUMBER.match(norm)
        if m:
            return _num(m.group(1))
    return None


def extract_people(norm: str, awaiting: bool = False) -> Optional[int]:
    m = _PEOPLE_RE.search(norm) or _PEOPLE_RE2.search(norm)
    if m:
        return _num(m.group(1))
    if awaiting:
        m = _ONLY_NUMBER.match(norm)
        if m:
            return _num(m.group(1))
    return None


def extract_vehicle(norm: str) -> Optional[str]:
    for v in VEHICLES:
        for alias in [v["name"].lower(), *v["aliases"]]:
            if re.search(rf"(?<![a-z]){re.escape(alias)}", norm):
                return v["name"]
    return None


def infer_trip_type(norm: str, to_city: Optional[str], pilgrimage_places: set) -> str:
    if re.search(r"darshan|pilgrim|yatra|mandir|temple|devotion|tirth|दर्शन|यात्रा|तीर्थ|मंदिर|मंदीर", norm):
        return "pilgrimage"
    if re.search(r"adventure|trek|trekking|rafting|ट्रेक", norm):
        return "adventure"
    if re.search(r"business|meeting|office|conference", norm):
        return "business"
    if re.search(r"family|parivar|kutumb|kutub|परिवार|कुटुंब|फॅमिली|फैमिली", norm):
        return "family"
    if to_city in pilgrimage_places:
        return "pilgrimage"
    return "leisure"


def infer_budget(norm: str) -> str:
    if re.search(r"luxury|premium|5 ?star|five star|shahi", norm):
        return "premium"
    if re.search(r"budget|sasta|cheap|economy|कमी खर्च", norm):
        return "budget"
    return "mid"


# -------------------------------------------------------------------- intents

_NEGATION = {"nahi", "nahin", "nai", "not", "no", "na", "nope", "naahi", "nako", "नहीं", "नही",
             "नाही", "नको", "अजून", "haven", "havent", "didn", "didnt", "isnt", "wasnt"}
_QUESTION_START = {"kya", "is", "has", "did", "was", "how", "can", "what", "when", "kab", "kay",
                   "kasa", "क्या", "काय", "कसे", "कसा", "कधी", "कब", "कैसे", "kaise", "will", "does"}

_CONFIRMED = [
    _roman("booked"),
    _roman("booking ho gayi", "booking ho gai", "booking ho gaya", "booking hogayi", "booking hogaya",
           "booking hui", "booking ho chuki", "booking done", "booking complete", "booking completed",
           "booking confirmed", "booking confirm ho gayi", "booking zali", "booking zala",
           "booking jhali", "booking jhala", "booking kela", "booking kele", "booking keli",
           "booking kar li", "booking kar liya", "booking kar di", "book kar liya", "book kar li",
           "book kar diya", "book kela", "book kele", "book keli", "maine book", "i booked",
           "i have booked", "ive booked", "confirmed", "booking is confirmed", "booking has been done"),
    re.compile(r"बुकिंग (?:झाली|झालं|झाले|हो गई|हो गयी|हो गया|केली|केलं|कन्फर्म)|बुक (?:केले|केलं|केली|कर लिया|कर ली)|कन्फर्म (?:झाले|झाली|हो गया|हो गई)"),
]
_PRICE_STRONG_ROMAN = _roman(
    "price", "prices", "pricing", "rate", "rates", "charge", "charges", "charged", "cost", "costs",
    "fee", "fees", "fare", "fares", "rupee", "rupees", "rupaye", "rupaiye", "rs", "inr", "paisa",
    "paise", "paisaa", "paisay", "kharcha", "kharch", "kimat", "kimmat", "kiraya", "bhada", "bhade",
    "discount", "offer", "offers", "package", "packages", "how much", "kitne ka", "kitne mein",
    "kitna lagega", "kitna padega", "kitne paise", "kiti lagel", "kiti padel", "kiti paise", "dar",
    "per km", "per day", "quote", "quotation", "estimate", "budget cab")
_PRICE_STRONG_DEV_TOKENS = {"दर", "रेट", "रेट्स", "दरात", "दराचे"}
_PRICE_STRONG_DEV_STEMS = ("किंमत", "किमत", "कीमत", "भाडे", "भाडं", "भाड़", "किराय", "किराए",
                           "रुपय", "रुपए", "रुपया", "पैसे", "पैसा", "खर्च", "चार्ज", "शुल्क",
                           "फीस", "डिस्काउंट", "ऑफर", "पॅकेज", "पैकेज")
_PRICE_PHRASES_DEV = ("कितने का", "कितना लगेगा", "कितना पड़ेगा", "किती लागेल", "किती पडेल",
                      "किती पैसे", "कितने पैसे")
_PRICE_WEAK = {"kitna", "kitne", "kitni", "kiti", "कितना", "कितने", "कितनी", "किती"}
# "kitna dur / kitne log / kiti vel": a quantity question that is not about money.
_NOT_PRICE_NEXT = {"dur", "door", "duur", "time", "samay", "km", "kms", "kilometer", "kilometre",
                   "kilometers", "log", "logo", "lok", "din", "dino", "days", "day", "seat", "seats",
                   "person", "persons", "jan", "ghante", "ghanta", "hours", "hour", "minute",
                   "minutes", "min", "der", "late", "distance", "fasla", "vel", "tas", "lamb",
                   "laamb", "raat", "people", "members", "passengers", "दूर", "दुर", "लांब", "वेळ",
                   "समय", "देर", "किमी", "किलोमीटर", "लोग", "लोक", "जण", "माणसे", "दिन", "दिवस",
                   "सीट", "घंटे", "तास", "अंतर", "दूरी", "रात", "वक्त", "मिनिट"}

_BOOKING_REQ = [
    _roman("book", "booking", "bookings", "reserve", "reservation", "confirm", "hire", "rent",
           "cab chahiye", "gaadi chahiye", "gadi chahiye", "cab pahije", "gadi pahije", "gaadi pahije",
           "taxi chahiye", "need a cab", "want a cab", "need a taxi", "want a taxi", "book karna",
           "book kara", "book kar do", "book karo", "book karaycha"),
    re.compile(r"बुकिंग|बुक करा|बुक करना|बुक करो|आरक्षण|गाडी हवी|गाडी पाहिजे|गाड़ी चाहिए|कैब चाहिए"),
]
_ITINERARY = [
    _roman("itinerary", "itinerery", "itenerary", "schedule", "yojana", "plan karo", "plan banao",
           "plan bana", "plan kara", "plan de", "plan chahiye", "plan karna", "plan karaycha",
           "plan banva", "trip plan", "tour plan", "travel plan", "safar plan", "yatra plan",
           "day wise", "daywise", "plan my trip", "plan a trip", "make a plan", "plan for"),
    re.compile(rf"(?<![a-z0-9]){_NUM}\s*(?:din|days?|day|दिन|दिवस)\s*(?:ka|ki|cha|chi|che|का|ची|चा)?\s*(?:plan|trip|tour|itinerary|प्लान|प्लॅन)"),
    re.compile(r"योजना|प्लॅन|प्लान|कार्यक्रम"),
]
_HOTEL = [
    _roman("hotel", "hotels", "stay", "where to stay", "accommodation", "lodge", "lodging", "resort",
           "resorts", "dharamshala", "rahane", "rahne", "rehne", "mukkam", "night stay", "guest house",
           "guesthouse", "homestay"),
    re.compile(r"होटल|होटेल|हॉटेल|रहने|राहण्य|राहायची|राहायला|मुक्काम|धर्मशाला|लॉज|रिसॉर्ट|ठहरने|रुकने"),
]
_ROUTE = [
    _roman("kitna dur", "kitna door", "kitna duur", "kitni dur", "kitni door", "kiti dur", "kiti door",
           "kiti duur", "kiti lamb", "how far", "distance", "time lagega", "kitna time", "kitna samay",
           "kiti vel", "kiti time", "how long", "driving time", "travel time", "route", "rasta",
           "raasta", "directions", "kitne km", "kiti km", "kitni der", "kitna der", "dur aahe",
           "door hai", "km dur", "km door", "how many km", "how many kilometres"),
    re.compile(r"दूर|दुर|लांब|अंतर|दूरी|किती वेळ|कितना समय|कितना वक्त|रस्ता|रास्ता|मार्ग|रूट|किमी|किलोमीटर"),
]
_VEHICLE = [
    _roman("konti gaadi", "konti gadi", "kon si gaadi", "konsi gaadi", "kaun si gaadi", "which cab",
           "which car", "which vehicle", "what cab", "what car", "what vehicle", "vehicle", "vehicles",
           "seats", "seater", "seating", "kitne log", "kiti jan", "kitne lok", "gaadi", "gadi", "gaadiya", "gaadiyan", "gaadiyaan", "gadiyan",
           "innova", "crysta", "ertiga", "dzire", "swift", "tempo", "traveller", "traveler", "sedan",
           "suv", "van", "bus", "fleet", "capacity"),
    re.compile(r"गाडी|गाड़ी|गाड्या|वाहन|सीट|इनोव्हा|इनोवा|टेम्पो|एर्टिगा|डिझायर|किती जण|कितने लोग|क्षमता"),
]
_DEST_STRONG = [
    _roman("places to visit", "place to visit", "things to do", "tourist", "tourists", "sightseeing",
           "attractions", "best time", "weather", "climate", "famous", "ghumne", "dekhne", "visit",
           "temple", "mandir", "darshan", "beach", "fort", "waterfall", "hill station", "mausam",
           "temperature", "kab jana chahiye", "ghumne ki jagah", "history", "timings", "timing",
           "aarti", "worth visiting", "kya kya", "famous for"),
    re.compile(r"प्रसिद्ध|पाहण्यासारख|देखने लायक|घूमने|फिरण्य|हवामान|मौसम|मंदिर|मंदीर|दर्शन|समुद्रकिनारा|किल्ला|सर्वोत्तम वेळ|सबसे अच्छा समय|कधी जावे|कब जाएं|कब जाएँ"),
]
_DEST_WEAK = [
    _roman("kya hai", "kay aahe", "tell me about", "about", "information", "info"),
    re.compile(r"क्या है|काय आहे|क्या खास|माहिती|जानकारी"),
]
_GREETING = [
    _roman("hello", "hi", "hii", "hiii", "hey", "heyy", "namaste", "namaskar", "namaskaar", "pranam",
           "good morning", "good afternoon", "good evening", "jai shri krishna", "ram ram"),
    re.compile(r"नमस्ते|नमस्कार|प्रणाम|राम राम|जय श्री"),
]
_TRAVEL_WORDS = _roman(
    "cab", "cabs", "taxi", "car", "trip", "tour", "travel", "safar", "yatra", "ride", "journey",
    "drive", "driver", "pickup", "pick up", "drop", "luggage", "vacation", "holiday", "outstation",
    "airport", "railway", "station", "obii", "booking")


def _any(patterns, text: str) -> bool:
    return any(p.search(text) for p in patterns)


def _is_confirmed(raw: str, norm: str) -> bool:
    if not _any(_CONFIRMED, norm):
        return False
    toks = tokens(norm)
    if "?" in raw or "？" in raw or (toks and toks[0] in _QUESTION_START):
        return False
    return not any(t in _NEGATION for t in toks)


def _pricing(norm: str) -> int:
    """2 = an explicit money word ("rate", "price", "किंमत"), 1 = only a bare
    "kitna/kiti" that is not clearly about distance, time, people or days, 0 = none."""
    if _PRICE_STRONG_ROMAN.search(norm) or any(p in norm for p in _PRICE_PHRASES_DEV):
        return 2
    toks = tokens(norm)
    for t in toks:
        if t in _PRICE_STRONG_DEV_TOKENS or (_DEV.match(t) and any(t.startswith(s) for s in _PRICE_STRONG_DEV_STEMS)):
            return 2
    for i, t in enumerate(toks):
        if t in _PRICE_WEAK:
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            if nxt not in _NOT_PRICE_NEXT:
                return 1
    return 0


@dataclass
class Intent:
    name: str
    pricing_also: bool = False   # a price question rode along with the main intent


def classify(raw: str, places_found: bool, word_count: Optional[int] = None) -> Intent:
    """
    The intent of one message. Order matters: confirmation before booking,
    pricing before everything that merely mentions money.
    """
    norm = normalize(raw)
    if _is_confirmed(raw, norm):
        return Intent("booking_confirmed")

    price_level = _pricing(norm)
    price = price_level > 0
    booking = _any(_BOOKING_REQ, norm)
    itinerary = _any(_ITINERARY, norm)
    hotel = _any(_HOTEL, norm)
    route = _any(_ROUTE, norm)
    vehicle = _any(_VEHICLE, norm)
    dest = _any(_DEST_STRONG, norm) or (places_found and _any(_DEST_WEAK, norm))

    if booking:
        return Intent("booking_request")
    info = ("itinerary_request" if itinerary else "hotel_query" if hotel else
            "route_query" if route else "vehicle_query" if vehicle else
            "destination_info" if dest else None)
    # A plain money question that merely mentions a vehicle or a place is a
    # price question, not a vehicle or destination one.
    if info in ("vehicle_query", "destination_info") and price_level == 2:
        return Intent("pricing_query")
    if info:
        return Intent(info, pricing_also=price)
    if price:
        return Intent("pricing_query")

    words = word_count if word_count is not None else len(tokens(norm))
    if _any(_GREETING, norm) and words <= 6:
        return Intent("greeting")
    return Intent("unclear")


def looks_travel_related(norm: str) -> bool:
    return bool(_TRAVEL_WORDS.search(norm))
