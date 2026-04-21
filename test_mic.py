# test_mic.py
"""
Test your microphone and speech recognition
Run this first to ensure everything works
"""

import speech_recognition as sr

def test_microphone():
    """Test if microphone is working"""
    print("\n" + "="*50)
    print("🎤 Microphone Test")
    print("="*50)
    
    # List all microphones
    print("\nAvailable microphones:")
    try:
        mics = sr.Microphone.list_microphone_names()
        if mics:
            for i, mic in enumerate(mics):
                print(f"  {i}: {mic}")
        else:
            print("  No microphones found!")
    except Exception as e:
        print(f"  Error listing microphones: {e}")
    
    # Test default microphone
    print("\n" + "-"*50)
    print("Testing default microphone...")
    print("Please speak something in 3 seconds...")
    print("-"*50)
    
    recognizer = sr.Recognizer()
    
    try:
        with sr.Microphone() as source:
            print("\n🔧 Adjusting for ambient noise...")
            recognizer.adjust_for_ambient_noise(source, duration=2)
            print("✅ Ambient noise adjustment complete")
            
            print("\n🎤 Listening now... (speak clearly)")
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
            print("✅ Audio captured successfully")
            
        print("\n🔄 Sending to Google for recognition...")
        
        # Try Hindi first
        try:
            text = recognizer.recognize_google(audio, language='hi-IN')
            print(f"\n✅ Recognized (Hindi): {text}")
        except:
            # Then English
            try:
                text = recognizer.recognize_google(audio, language='en-IN')
                print(f"\n✅ Recognized (English): {text}")
            except sr.UnknownValueError:
                print("\n❌ Could not understand audio")
            except sr.RequestError as e:
                print(f"\n❌ Recognition service error: {e}")
        
    except sr.WaitTimeoutError:
        print("\n⏰ No speech detected (timeout)")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    
    print("\n" + "="*50)
    print("Test complete")
    print("="*50)

def test_speech_to_text_loop():
    """Continuous test mode"""
    print("\n" + "="*50)
    print("Continuous Speech Test Mode")
    print("Speak anything - press Ctrl+C to exit")
    print("="*50)
    
    recognizer = sr.Recognizer()
    
    try:
        with sr.Microphone() as source:
            print("\n🔧 Calibrating microphone...")
            recognizer.adjust_for_ambient_noise(source, duration=2)
            
            while True:
                print("\n🎤 Listening...")
                try:
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
                    print("🔄 Recognizing...")
                    
                    # Try multiple languages
                    text = None
                    
                    # Hindi
                    try:
                        text = recognizer.recognize_google(audio, language='hi-IN')
                        print(f"📝 Hindi: {text}")
                    except:
                        pass
                    
                    # English
                    if not text:
                        try:
                            text = recognizer.recognize_google(audio, language='en-IN')
                            print(f"📝 English: {text}")
                        except sr.UnknownValueError:
                            print("❌ Could not understand")
                        except sr.RequestError as e:
                            print(f"❌ API Error: {e}")
                            
                except sr.WaitTimeoutError:
                    print("⏰ No speech detected")
                    
    except KeyboardInterrupt:
        print("\n\n✅ Test ended")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    print("Choose test mode:")
    print("1. Quick microphone test")
    print("2. Continuous speech test")
    
    choice = input("Enter choice (1 or 2): ").strip()
    
    if choice == '1':
        test_microphone()
    elif choice == '2':
        test_speech_to_text_loop()
    else:
        print("Invalid choice")