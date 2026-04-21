# test_json.py
"""
Simple test script to verify JSON generation works
"""

from bot import AINetaBot
from complaint import ComplaintData
import os
import json
from dotenv import load_dotenv

load_dotenv()

def test_json_generation():
    """Test if JSON generation works without API calls"""
    
    print("=" * 50)
    print("TESTING JSON GENERATION")
    print("=" * 50)
    
    # Get API key
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("❌ ERROR: GROQ_API_KEY not found in .env file")
        return
    
    print("✅ API key found")
    
    # Initialize bot
    bot = AINetaBot(api_key)
    print("✅ Bot initialized")
    
    # Create a test complaint
    complaint = ComplaintData()
    complaint.issue_type = "safai"
    complaint.description = "10 din se safai nahi hui hai"
    complaint.location = "test area, shivpuri"
    complaint.photo_available = False
    complaint.photo_path = None
    
    print("\n📋 Test Complaint Data:")
    print(f"   Issue Type: {complaint.issue_type}")
    print(f"   Description: {complaint.description}")
    print(f"   Location: {complaint.location}")
    print(f"   Photo: {'✅' if complaint.photo_available else '❌'}")
    
    # Generate JSON
    print("\n🔄 Generating JSON...")
    result = bot._generate_complaint_json(
        user_id="test_user_123",
        phone="9876543210",
        complaint_data=complaint
    )
    
    print("\n" + "=" * 50)
    print("RESULTS:")
    print("=" * 50)
    
    print(f"Response Type: {result.get('type')}")
    print(f"Reply Message: {result.get('reply')}")
    
    if result.get('json'):
        print("\n✅ JSON GENERATED SUCCESSFULLY!")
        print("\nJSON Content:")
        print(json.dumps(result['json'], indent=2, ensure_ascii=False))
        
        # Save to a test file
        with open('test_output.json', 'w', encoding='utf-8') as f:
            json.dump(result['json'], f, indent=2, ensure_ascii=False)
        print("\n✅ JSON also saved to test_output.json")
    else:
        print("\n❌ No JSON generated!")
        if result.get('error'):
            print(f"Error: {result['error']}")
    
    print("=" * 50)
    return result

def test_complaint_flow():
    """Test the complete complaint flow"""
    
    print("\n" + "=" * 50)
    print("TESTING COMPLETE COMPLAINT FLOW")
    print("=" * 50)
    
    api_key = os.getenv("GROQ_API_KEY")
    bot = AINetaBot(api_key)
    user_id = "flow_test_user"
    
    # Simulate a conversation flow
    messages = [
        ("complaint karni hai", "Should ask for confirmation"),
        ("ha", "Should start collection"),
        ("safai", "Should ask for description"),
        ("10 din se safai nahi hui", "Should ask for location"),
        ("test area", "Should ask for photo"),
        ("nahi", "Should show summary"),
        ("ha", "Should generate JSON")
    ]
    
    print("\n🔄 Simulating conversation flow...\n")
    
    for msg, expected in messages:
        print(f"User: {msg}")
        response = bot.process_message(
            user_message=msg,
            user_id=user_id,
            phone="9876543210"
        )
        print(f"Bot Type: {response.get('type')}")
        print(f"Bot: {response.get('reply')[:100]}...")
        print(f"→ Expected: {expected}")
        print("-" * 40)
        
        if response.get('type') == 'complaint_registered':
            print("\n✅ COMPLAINT REGISTERED! JSON GENERATED!")
            if response.get('json'):
                print("\nJSON Preview:")
                print(json.dumps(response['json'], indent=2, ensure_ascii=False)[:500])
            break
    
    print("=" * 50)

if __name__ == "__main__":
    print("Choose test:")
    print("1. Test JSON generation only")
    print("2. Test complete complaint flow")
    
    choice = input("Enter choice (1 or 2): ").strip()
    
    if choice == "1":
        test_json_generation()
    elif choice == "2":
        test_complaint_flow()
    else:
        print("Invalid choice")