# test_groq.py
from groq import Groq
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('GROQ_API_KEY')
print(f"API Key found: {'Yes' if api_key else 'No'}")
print(f"API Key starts with: {api_key[:10]}...")

try:
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "Say 'Hello' in Hindi"}],
        max_tokens=10
    )
    print("✅ API working! Response:", response.choices[0].message.content)
except Exception as e:
    print(f"❌ Error: {e}")