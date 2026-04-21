 # terminal_test.py
"""
Simple terminal-based test for AI NETA bot
Run this to test the bot directly in terminal
"""

from bot import AINetaBot
from dotenv import load_dotenv
import os
import json

load_dotenv()

def print_bot_response(response):
    """Pretty print bot response"""
    print(f"\n🤖 [Type: {response.get('type')}]")
    print(f"💬 {response.get('reply')}")
    
    if response.get('json'):
        print("\n📋 JSON OUTPUT:")
        print(json.dumps(response.get('json'), indent=2, ensure_ascii=False))
        print("-" * 50)

def main():
    # Get API key
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("❌ Error: GROQ_API_KEY not found in .env file")
        return
    
    # Initialize bot
    bot = AINetaBot(api_key)
    user_id = "terminal_user"
    phone = "9876543210"
    
    print("=" * 60)
    print("AI NETA - Terminal Test")
    print("=" * 60)
    print("Commands:")
    print("  /exit  - Exit")
    print("  /reset - Reset conversation")
    print("  /state - Show current state")
    print("=" * 60)
    
    print("\n🤖 Bot initialized! Start chatting...\n")
    
    while True:
        try:
            # Get user input
            user_input = input("👤 You: ").strip()
            
            if user_input.lower() == '/exit':
                print("\n👋 Goodbye!")
                break
            elif user_input.lower() == '/reset':
                bot = AINetaBot(api_key)
                print("\n🔄 Conversation reset!\n")
                continue
            elif user_input.lower() == '/state':
                print(f"\n📊 Current State for {user_id}:")
                print(f"  Active complaint: {bot.active_complaints.get(user_id) is not None}")
                print(f"  Waiting photo: {bot.waiting_for_photo.get(user_id, False)}")
                print(f"  Waiting confirmation: {bot.waiting_for_confirmation.get(user_id, False)}")
                print(f"  Language: {bot.user_language.get(user_id, 'unknown')}\n")
                continue
            elif not user_input:
                continue
            
            # Process message
            response = bot.process_message(
                user_message=user_input,
                user_id=user_id,
                phone=phone
            )
            
            # Print response
            print_bot_response(response)
            
            # If complaint registered, show where JSON is saved
            if response.get('type') == 'complaint_registered':
                print("\n✅ Complaint registered! Check complaints_data.json")
                
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()