 # voice_complaint_bot.py
"""
USER VOICE BOLTA HAI → TEXT MEIN CONVERT → BOT NORMAL KAAM KARTA HAI
"""

from bot import AINetaBot
from dotenv import load_dotenv
import os
import speech_recognition as sr

load_dotenv()

# ===== 1. VOICE → TEXT CONVERTER =====
def suno_aur_samjho():
    """Bas user ki voice ko text mein convert karo"""
    r = sr.Recognizer()
    
    with sr.Microphone() as source:
        print("\n🎤 Boliye... (speak now)")
        r.adjust_for_ambient_noise(source)
        audio = r.listen(source, timeout=5, phrase_time_limit=10)
    
    print("🔄 Convert kar raha hoon...")
    
    # Pehle Hindi mein try
    try:
        text = r.recognize_google(audio, language='hi-IN')
        print(f"📝 Aapne kaha: {text}")
        return text
    except:
        pass
    
    # Phir English mein try
    try:
        text = r.recognize_google(audio, language='en-IN')
        print(f"📝 You said: {text}")
        return text
    except sr.UnknownValueError:
        print("❌ Samajh nahi aaya")
        return None
    except sr.RequestError:
        print("❌ Google service error")
        return None

# ===== 2. BOT SHURU =====
api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    print("❌ API key nahi mila! .env file check karo")
    exit()

bot = AINetaBot(api_key)
user_id = "voice_user"

print("\n" + "="*60)
print("🤖 AI NETA - VOICE COMPLAINT SYSTEM")
print("="*60)
print("👉 Aap boliye, main complaint register karunga")
print("👉 'exit' ya 'बंद करो' bolne par band hoga")
print("="*60)

# ===== 3. MAIN LOOP - YAHI PAR SAB KUCCH NORMAL HAI =====
while True:
    # Step 1: Voice se text lo
    user_text = suno_aur_samjho()
    
    if user_text is None:
        print("⏳ Dobara boliye...")
        continue
    
    # Step 2: Exit check
    if user_text.lower() in ['exit', 'quit', 'bye', 'बंद करो', 'अलविदा', 'band']:
        print("🤖 Bot: अलविदा! Goodbye!")
        break
    
    # Step 3: Bot ko text do - YEH NORMAL FLOW HAI!
    print("⏳ Bot soch raha hai...")
    response = bot.process_message(user_text, user_id)
    
    # Step 4: Bot ka jawab dikhao - NORMAL TEXT!
    print(f"\n🤖 Bot: {response['reply']}")
    
    # Agar complaint register hui to details dikhao
    if response.get('type') == 'complaint_registered':
        complaint_data = response.get('json', {}).get('complaint', {})
        complaint_id = complaint_data.get('complaint_id', '')
        department = complaint_data.get('department', {}).get('name', '')
        
        print(f"\n✅ COMPLAINT REGISTERED!")
        print(f"📋 ID: {complaint_id}")
        print(f"🏢 Department: {department}")
    
    print("-" * 50)