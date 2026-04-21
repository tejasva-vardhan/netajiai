# test_fixed.py — quick Groq connectivity check (no keys in source).
from groq import Groq
import os

api_key = (os.getenv("GROQ_API_KEY") or "YOUR_API_KEY_HERE").strip()
if not api_key or api_key == "YOUR_API_KEY_HERE":
    raise SystemExit("Set GROQ_API_KEY in your environment or .env before running this script.")

try:
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "Say hello in Hindi"}],
        max_tokens=20,
    )
    print("✅ SUCCESS! Key works.")
    print(f"Response: {response.choices[0].message.content}")
except Exception as e:
    print(f"❌ Failed: {e}")
