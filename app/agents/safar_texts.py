"""
Fixed, human-checked wording for every Safar reply that does not need a model.

Languages: en, hi (Hindi/Hinglish in Roman letters), hi_dev (Hindi in
Devanagari), mr (Marathi, Devanagari). Prices, bookings and route facts are
always built from these templates plus verified data, never improvised.

NOTE FOR THE OWNER: the Marathi and Devanagari Hindi lines were written by an
AI model. Have a native speaker read them once before launch.
"""

from typing import Optional

LANGS = ("en", "hi", "hi_dev", "mr")

T: dict[str, dict[str, str]] = {
    "greeting": {
        "en": "Hello! I'm Safar, the travel assistant of Obii Cabs 🙏 Ask me about routes, vehicles or trip planning. How can I help?",
        "hi": "Namaste! Main Safar hu, Obii Cabs ka travel assistant 🙏 Route, vehicle ya trip planning ke baare mein puchiye. Main kaise madad kar sakta hu?",
        "hi_dev": "नमस्ते! मैं Safar हूँ, Obii Cabs का ट्रैवल असिस्टेंट 🙏 रूट, गाड़ी या ट्रिप प्लानिंग के बारे में पूछिए। मैं कैसे मदद कर सकता हूँ?",
        "mr": "नमस्ते! मी Safar आहे, Obii Cabs चा ट्रॅव्हल असिस्टंट 🙏 रूट, गाडी किंवा ट्रिप प्लॅनिंगबद्दल विचारा. मी कशी मदत करू?",
    },
    "greeting_named": {
        "en": "Hello {name}! I'm Safar, the travel assistant of Obii Cabs 🙏 How can I help you today?",
        "hi": "Namaste {name}! Main Safar hu, Obii Cabs ka travel assistant 🙏 Aaj main aapki kaise madad kar sakta hu?",
        "hi_dev": "नमस्ते {name}! मैं Safar हूँ, Obii Cabs का ट्रैवल असिस्टेंट 🙏 आज मैं आपकी कैसे मदद कर सकता हूँ?",
        "mr": "नमस्ते {name}! मी Safar आहे, Obii Cabs चा ट्रॅव्हल असिस्टंट 🙏 आज मी तुम्हाला कशी मदत करू?",
    },
    "greeting_returning": {
        "en": " Last time you were asking about {from_city} to {to_city}. Shall we continue with that trip?",
        "hi": " Pichli baar aap {from_city} se {to_city} ke baare mein pooch rahe the. Kya us trip par aage badhein?",
        "hi_dev": " पिछली बार आप {from_city} से {to_city} के बारे में पूछ रहे थे। क्या उस ट्रिप पर आगे बढ़ें?",
        "mr": " मागच्या वेळी तुम्ही {from_city} ते {to_city} बद्दल विचारत होता. त्या ट्रिपबद्दल पुढे जाऊया का?",
    },
    "pricing": {
        "en": "For rates, please call us: 📞 {phone}",
        "hi": "Rates ke liye seedha call karein: 📞 {phone}",
        "hi_dev": "रेट्स के लिए सीधे कॉल करें: 📞 {phone}",
        "mr": "दर जाणून घेण्यासाठी आमच्याशी संपर्क करा: 📞 {phone}",
    },
    "booking_redirect": {
        "en": "To book, please call us:\n📞 {phone}\nAfter you've booked, I'll suggest your itinerary and hotels! 😊",
        "hi": "Booking ke liye call karein:\n📞 {phone}\nCall ke baad main aapka itinerary aur hotels suggest karunga! 😊",
        "hi_dev": "बुकिंग के लिए कॉल करें:\n📞 {phone}\nकॉल के बाद मैं आपका इटिनेररी और होटल सुझाऊँगा! 😊",
        "mr": "बुकिंगसाठी कृपया कॉल करा:\n📞 {phone}\nकॉलनंतर मी तुमचा प्रवास कार्यक्रम आणि हॉटेल्स सुचवेन! 😊",
    },
    "booking_ack": {
        "en": "That's great! Now I can help you plan your trip! How many days is the trip? 😊",
        "hi": "Bahut achha! Ab main aapki trip plan karne mein help karunga! Kitne din ka trip hai? 😊",
        "hi_dev": "बहुत अच्छा! अब मैं आपकी ट्रिप प्लान करने में मदद करूँगा! कितने दिन का ट्रिप है? 😊",
        "mr": "खूप छान! आता मी तुमची ट्रिप प्लॅन करायला मदत करेन! किती दिवसांची ट्रिप आहे? 😊",
    },
    "itinerary_need_booking": {
        "en": "Please confirm your booking first, then I'll make your full plan! 📞 {phone}",
        "hi": "Pehle booking confirm karein, phir main aapka pura plan banaunga! 📞 {phone}",
        "hi_dev": "पहले बुकिंग कन्फर्म करें, फिर मैं आपका पूरा प्लान बनाऊँगा! 📞 {phone}",
        "mr": "आधी बुकिंग कन्फर्म करा, मग मी तुमचा पूर्ण प्लॅन बनवेन! 📞 {phone}",
    },
    "hotel_need_booking": {
        "en": "Please confirm your booking first, then I'll suggest hotels! 📞 {phone}",
        "hi": "Pehle booking confirm karein, phir main hotels suggest karunga! 📞 {phone}",
        "hi_dev": "पहले बुकिंग कन्फर्म करें, फिर मैं होटल सुझाऊँगा! 📞 {phone}",
        "mr": "आधी बुकिंग कन्फर्म करा, मग मी हॉटेल्स सुचवेन! 📞 {phone}",
    },
    "oos": {
        "en": "I can only help with Obii Cabs' travel services! Ask me about routes, vehicles or trip planning 😊",
        "hi": "Main sirf Obii Cabs ki travel services ke baare mein help kar sakta hu! Route, vehicle ya trip planning ke liye puchiye 😊",
        "hi_dev": "मैं सिर्फ़ Obii Cabs की ट्रैवल सर्विसेज़ के बारे में मदद कर सकता हूँ! रूट, गाड़ी या ट्रिप प्लानिंग के लिए पूछिए 😊",
        "mr": "मी फक्त Obii Cabs च्या प्रवास सेवांबद्दल मदत करू शकतो! रूट, गाडी किंवा ट्रिप प्लॅनिंगबद्दल विचारा 😊",
    },
    "ask_places": {
        "en": "Which route? Tell me the starting city and the destination, for example Pune to Shirdi.",
        "hi": "Kaun sa route? Shuruwati shehar aur manzil bataiye, jaise Pune se Shirdi.",
        "hi_dev": "कौन सा रूट? शुरुआती शहर और मंज़िल बताइए, जैसे Pune से Shirdi।",
        "mr": "कोणता मार्ग? सुरुवातीचे शहर आणि गंतव्य सांगा, उदा. Pune ते Shirdi.",
    },
    "ask_days": {
        "en": "How many days is the trip? 😊",
        "hi": "Kitne din ka trip hai? 😊",
        "hi_dev": "कितने दिन का ट्रिप है? 😊",
        "mr": "किती दिवसांची ट्रिप आहे? 😊",
    },
    "ask_people": {
        "en": "How many people are travelling?",
        "hi": "Kitne log travel kar rahe hain?",
        "hi_dev": "कितने लोग यात्रा कर रहे हैं?",
        "mr": "किती जण प्रवास करणार आहेत?",
    },
    "ask_dest": {
        "en": "Which place would you like to know about?",
        "hi": "Kis jagah ke baare mein jaanna chahte hain?",
        "hi_dev": "किस जगह के बारे में जानना चाहते हैं?",
        "mr": "कोणत्या ठिकाणाबद्दल माहिती हवी आहे?",
    },
    "route_answer": {
        "en": "{from_city} to {to_city} is about {km} km, roughly {dur} by road (as per Google Maps). Shall I suggest a vehicle for your group?",
        "hi": "{from_city} se {to_city} lagbhag {km} km door hai, road se takriban {dur} lagenge (Google Maps ke hisaab se). Aapke group ke liye gaadi suggest karu?",
        "hi_dev": "{from_city} से {to_city} लगभग {km} किमी दूर है, सड़क से करीब {dur} लगेंगे (Google Maps के अनुसार)। आपके ग्रुप के लिए गाड़ी सुझाऊँ?",
        "mr": "{from_city} ते {to_city} अंतर सुमारे {km} किमी आहे, रस्त्याने साधारण {dur} लागतील (Google Maps नुसार). तुमच्या ग्रुपसाठी गाडी सुचवू का?",
    },
    "route_notfound": {
        "en": "I couldn't find a road route between {from_city} and {to_city}. Please check the city names.",
        "hi": "{from_city} aur {to_city} ke beech road route nahi mila. Kripya shehar ke naam check karein.",
        "hi_dev": "{from_city} और {to_city} के बीच सड़क मार्ग नहीं मिला। कृपया शहरों के नाम जाँच लें।",
        "mr": "{from_city} आणि {to_city} यांच्यातील रस्ता सापडला नाही. कृपया शहरांची नावे तपासा.",
    },
    "route_unavailable": {
        "en": "I can't fetch route details right now, so I won't guess. Please call us: 📞 {phone}",
        "hi": "Abhi route ki jaankari nahi mil pa rahi, isliye andaza nahi lagaunga. Kripya call karein: 📞 {phone}",
        "hi_dev": "अभी रूट की जानकारी नहीं मिल पा रही, इसलिए अंदाज़ा नहीं लगाऊँगा। कृपया कॉल करें: 📞 {phone}",
        "mr": "सध्या मार्गाची माहिती मिळवता येत नाही, म्हणून अंदाज लावणार नाही. कृपया कॉल करा: 📞 {phone}",
    },
    "vehicle_for_group": {
        "en": "For {n} people, a {name} (up to {seats} passengers) will be comfortable. Please call to confirm availability: 📞 {phone}",
        "hi": "{n} logon ke liye {name} (zyada se zyada {seats} passengers) theek rahegi. Availability confirm karne ke liye call karein: 📞 {phone}",
        "hi_dev": "{n} लोगों के लिए {name} (ज़्यादा से ज़्यादा {seats} यात्री) ठीक रहेगी। उपलब्धता के लिए कॉल करें: 📞 {phone}",
        "mr": "{n} जणांसाठी {name} (जास्तीत जास्त {seats} प्रवासी) योग्य राहील. उपलब्धतेसाठी कृपया कॉल करा: 📞 {phone}",
    },
    "vehicle_too_many": {
        "en": "{n} people will need more than one vehicle or a larger van. Please call us to arrange it: 📞 {phone}",
        "hi": "{n} logon ke liye ek se zyada gaadi ya badi van chahiye hogi. Arrangement ke liye call karein: 📞 {phone}",
        "hi_dev": "{n} लोगों के लिए एक से ज़्यादा गाड़ी या बड़ी वैन लगेगी। व्यवस्था के लिए कॉल करें: 📞 {phone}",
        "mr": "{n} जणांसाठी एकापेक्षा जास्त गाड्या किंवा मोठी व्हॅन लागेल. व्यवस्थेसाठी कॉल करा: 📞 {phone}",
    },
    "vehicle_list": {
        "en": "Obii Cabs vehicles: {list}. Tell me how many people are travelling and I'll suggest one. For availability call 📞 {phone}",
        "hi": "Obii Cabs ki gaadiyan: {list}. Kitne log travel kar rahe hain batayiye, main sahi gaadi suggest karunga. Availability ke liye call karein 📞 {phone}",
        "hi_dev": "Obii Cabs की गाड़ियाँ: {list}। कितने लोग यात्रा कर रहे हैं बताइए, मैं सही गाड़ी सुझाऊँगा। उपलब्धता के लिए कॉल करें 📞 {phone}",
        "mr": "Obii Cabs च्या गाड्या: {list}. किती जण प्रवास करणार ते सांगा, मी योग्य गाडी सुचवेन. उपलब्धतेसाठी 📞 {phone}",
    },
    "vehicle_named": {
        "en": "{name} seats up to {seats} passengers. {fit}Please call to confirm availability: 📞 {phone}",
        "hi": "{name} mein zyada se zyada {seats} passengers baith sakte hain. {fit}Availability ke liye call karein: 📞 {phone}",
        "hi_dev": "{name} में ज़्यादा से ज़्यादा {seats} यात्री बैठ सकते हैं। {fit}उपलब्धता के लिए कॉल करें: 📞 {phone}",
        "mr": "{name} मध्ये जास्तीत जास्त {seats} प्रवासी बसतात. {fit}उपलब्धतेसाठी कॉल करा: 📞 {phone}",
    },
    "fit_ok": {
        "en": "It's enough for {n} people. ",
        "hi": "{n} logon ke liye ye kaafi hai. ",
        "hi_dev": "{n} लोगों के लिए यह काफ़ी है। ",
        "mr": "{n} जणांसाठी ही पुरेशी आहे. ",
    },
    "fit_no": {
        "en": "It's not enough for {n} people. ",
        "hi": "{n} logon ke liye ye kaafi nahi hai. ",
        "hi_dev": "{n} लोगों के लिए यह काफ़ी नहीं है। ",
        "mr": "{n} जणांसाठी ही पुरेशी नाही. ",
    },
    "itinerary_head": {
        "en": "Here is your {days}-day plan, {from_city} to {to_city}:",
        "hi": "Ye raha aapka {days} din ka plan, {from_city} se {to_city}:",
        "hi_dev": "यह रहा आपका {days} दिन का प्लान, {from_city} से {to_city}:",
        "mr": "तुमचा {days} दिवसांचा प्लॅन, {from_city} ते {to_city}:",
    },
    "itinerary_day": {
        "en": "Day {n}: {title}",
        "hi": "Din {n}: {title}",
        "hi_dev": "दिन {n}: {title}",
        "mr": "दिवस {n}: {title}",
    },
    "itinerary_foot": {
        "en": "Total distance {km} km (about {dur}). You can download the PDF from your itinerary page. For rates and booking call 📞 {phone}",
        "hi": "Total doori {km} km (takriban {dur}). Itinerary ka PDF aap apne itinerary page se download kar sakte hain. Rates aur booking ke liye call karein 📞 {phone}",
        "hi_dev": "कुल दूरी {km} किमी (करीब {dur})। इटिनेररी का PDF आप अपने इटिनेररी पेज से डाउनलोड कर सकते हैं। रेट्स और बुकिंग के लिए कॉल करें 📞 {phone}",
        "mr": "एकूण अंतर {km} किमी (सुमारे {dur}). PDF तुम्ही तुमच्या इटिनररी पेजवरून डाउनलोड करू शकता. दर आणि बुकिंगसाठी कॉल करा 📞 {phone}",
    },
    "itinerary_failed": {
        "en": "I couldn't prepare the plan right now. Please try again, or call us: 📞 {phone}",
        "hi": "Abhi plan taiyaar nahi ho paya. Kripya dobara try karein ya call karein: 📞 {phone}",
        "hi_dev": "अभी प्लान तैयार नहीं हो पाया। कृपया दोबारा कोशिश करें या कॉल करें: 📞 {phone}",
        "mr": "सध्या प्लॅन तयार करता आला नाही. कृपया पुन्हा प्रयत्न करा किंवा कॉल करा: 📞 {phone}",
    },
    "days_range": {
        "en": "A trip can be from 1 to 30 days. How many days do you want?",
        "hi": "Trip 1 se 30 din ki ho sakti hai. Kitne din chahiye?",
        "hi_dev": "ट्रिप 1 से 30 दिन की हो सकती है। कितने दिन चाहिए?",
        "mr": "ट्रिप १ ते ३० दिवसांची असू शकते. किती दिवस हवेत?",
    },
    "people_range": {
        "en": "I can plan for 1 to 50 people. How many are travelling?",
        "hi": "Main 1 se 50 logon ke liye plan bana sakta hu. Kitne log hain?",
        "hi_dev": "मैं 1 से 50 लोगों के लिए प्लान बना सकता हूँ। कितने लोग हैं?",
        "mr": "मी १ ते ५० जणांसाठी प्लॅन करू शकतो. किती जण आहेत?",
    },
    "hotel_intro": {
        "en": "Hotel ideas for {to_city}:",
        "hi": "{to_city} ke liye hotel suggestions:",
        "hi_dev": "{to_city} के लिए होटल सुझाव:",
        "mr": "{to_city} साठी हॉटेल सूचना:",
    },
    "hotel_disclaimer": {
        "en": "These are only suggestions. Please book hotels yourself.",
        "hi": "Ye sirf suggestions hain. Hotel booking aap khud karein.",
        "hi_dev": "ये सिर्फ़ सुझाव हैं। होटल बुकिंग आप खुद करें।",
        "mr": "या फक्त सूचना आहेत. हॉटेल बुकिंग तुम्ही स्वतः करा.",
    },
    "hotel_none": {
        "en": "I couldn't find reliable hotel suggestions for {to_city} right now. Please call us: 📞 {phone}",
        "hi": "Abhi {to_city} ke liye bharosemand hotel suggestions nahi mile. Kripya call karein: 📞 {phone}",
        "hi_dev": "अभी {to_city} के लिए भरोसेमंद होटल सुझाव नहीं मिले। कृपया कॉल करें: 📞 {phone}",
        "mr": "सध्या {to_city} साठी खात्रीशीर हॉटेल सूचना मिळाल्या नाहीत. कृपया कॉल करा: 📞 {phone}",
    },
    "dest_unknown": {
        "en": "I don't have reliable information on that right now, and I'd rather not guess. You can call us: 📞 {phone}",
        "hi": "Iske baare mein mere paas abhi pakki jaankari nahi hai, isliye andaza nahi lagaunga. Aap call kar sakte hain: 📞 {phone}",
        "hi_dev": "इसके बारे में मेरे पास अभी पक्की जानकारी नहीं है, इसलिए अंदाज़ा नहीं लगाऊँगा। आप कॉल कर सकते हैं: 📞 {phone}",
        "mr": "याबद्दल माझ्याकडे सध्या खात्रीशीर माहिती नाही, म्हणून अंदाज लावणार नाही. तुम्ही आम्हाला कॉल करू शकता: 📞 {phone}",
    },
    "fallback": {
        "en": "Sorry, I can't give you an accurate answer right now. Please call us: 📞 {phone}",
        "hi": "Maaf kijiye, abhi main sahi jaankari nahi de pa raha. Kripya call karein: 📞 {phone}",
        "hi_dev": "माफ़ कीजिए, अभी मैं सही जानकारी नहीं दे पा रहा। कृपया कॉल करें: 📞 {phone}",
        "mr": "माफ करा, सध्या मी अचूक माहिती देऊ शकत नाही. कृपया कॉल करा: 📞 {phone}",
    },
}

SUGGESTIONS: dict[str, dict[str, list[str]]] = {
    "greeting": {
        "en": ["How far is Pune from Shirdi?", "Which vehicle suits my group?"],
        "hi": ["Pune se Shirdi kitna dur hai?", "Konsi gaadi suitable rahegi?"],
        "hi_dev": ["पुणे से शिर्डी कितनी दूर है?", "कौन सी गाड़ी ठीक रहेगी?"],
        "mr": ["पुणे ते शिर्डी किती दूर आहे?", "कोणती गाडी योग्य राहील?"],
    },
    "route": {
        "en": ["Will an Innova Crysta suit us?", "Do you need a 2-day itinerary?"],
        "hi": ["Innova Crysta suitable rahegi?", "2 din ka itinerary chahiye?"],
        "hi_dev": ["इनोवा क्रिस्टा ठीक रहेगी?", "2 दिन का इटिनेररी चाहिए?"],
        "mr": ["इनोव्हा क्रिस्टा योग्य राहील का?", "२ दिवसांचा प्रवास कार्यक्रम हवा का?"],
    },
    "vehicle": {
        "en": ["How far is my destination?", "I want to book"],
        "hi": ["Mera destination kitna dur hai?", "Booking karni hai"],
        "hi_dev": ["मेरी मंज़िल कितनी दूर है?", "बुकिंग करनी है"],
        "mr": ["माझे ठिकाण किती दूर आहे?", "बुकिंग करायची आहे"],
    },
    "booking": {
        "en": ["My booking is done", "How far is my destination?"],
        "hi": ["Booking ho gayi", "Mera destination kitna dur hai?"],
        "hi_dev": ["बुकिंग हो गई", "मेरी मंज़िल कितनी दूर है?"],
        "mr": ["बुकिंग झाली", "माझे ठिकाण किती दूर आहे?"],
    },
    "confirmed": {
        "en": ["Pune to Shirdi, 2 days, 4 people", "Suggest hotels"],
        "hi": ["Pune se Shirdi, 2 din, 4 log", "Hotels suggest karo"],
        "hi_dev": ["पुणे से शिर्डी, 2 दिन, 4 लोग", "होटल सुझाओ"],
        "mr": ["पुणे ते शिर्डी, २ दिवस, ४ जण", "हॉटेल सुचवा"],
    },
    "itinerary": {
        "en": ["Suggest hotels", "What are the best places to visit there?"],
        "hi": ["Hotels suggest karo", "Wahan ghumne ki best jagah konsi hain?"],
        "hi_dev": ["होटल सुझाओ", "वहाँ घूमने की सबसे अच्छी जगहें कौन सी हैं?"],
        "mr": ["हॉटेल सुचवा", "तिथे पाहण्यासारखी ठिकाणे कोणती?"],
    },
    "hotel": {
        "en": ["Make my itinerary", "Best time to visit?"],
        "hi": ["Itinerary banao", "Jaane ka best time kya hai?"],
        "hi_dev": ["इटिनेररी बनाओ", "जाने का सबसे अच्छा समय कौन सा है?"],
        "mr": ["प्रवास कार्यक्रम बनवा", "जाण्याची सर्वोत्तम वेळ कोणती?"],
    },
    "dest": {
        "en": ["How far is it from my city?", "Which vehicle should I take?"],
        "hi": ["Mere shehar se kitna dur hai?", "Konsi gaadi leni chahiye?"],
        "hi_dev": ["मेरे शहर से कितना दूर है?", "कौन सी गाड़ी लेनी चाहिए?"],
        "mr": ["माझ्या शहरापासून किती दूर आहे?", "कोणती गाडी घ्यावी?"],
    },
    "default": {
        "en": ["How far is Pune from Shirdi?", "Which vehicle suits my group?"],
        "hi": ["Pune se Shirdi kitna dur hai?", "Konsi gaadi suitable rahegi?"],
        "hi_dev": ["पुणे से शिर्डी कितनी दूर है?", "कौन सी गाड़ी ठीक रहेगी?"],
        "mr": ["पुणे ते शिर्डी किती दूर आहे?", "कोणती गाडी योग्य राहील?"],
    },
}


def t(key: str, lang: str, **kw) -> str:
    text = T[key].get(lang) or T[key]["en"]
    return text.format(**kw) if kw else text


def suggestions(group: str, lang: str) -> list[str]:
    return list((SUGGESTIONS.get(group) or SUGGESTIONS["default"]).get(lang) or SUGGESTIONS["default"]["en"])


def format_duration(minutes: int, lang: str) -> str:
    """'3 hours 20 mins' in the reply language. Digits stay Latin everywhere."""
    h, m = divmod(max(0, int(round(minutes))), 60)
    units = {
        "en": ("hour", "hours", "min", "mins"),
        "hi": ("ghanta", "ghante", "minute", "minute"),
        "hi_dev": ("घंटा", "घंटे", "मिनट", "मिनट"),
        "mr": ("तास", "तास", "मिनिट", "मिनिटे"),
    }[lang if lang in LANGS else "en"]
    parts = []
    if h:
        parts.append(f"{h} {units[0] if h == 1 else units[1]}")
    if m or not h:
        parts.append(f"{m} {units[2] if m == 1 else units[3]}")
    return " ".join(parts)


def phone_line(lang: str, phone: str) -> str:
    return t("pricing", lang, phone=phone)
