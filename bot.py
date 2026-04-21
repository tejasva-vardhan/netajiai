# bot.py
"""
AI NETA - Core Chatbot Class with Photo Support
"""

from groq import Groq
from complaint import ComplaintData
from utils import assign_department, is_complaint_intent
from datetime import datetime
import uuid
from typing import Dict, Any, Optional
import os
import shutil
import json
import re
import httpx

# Frontend sends this after user taps "Confirm Location" on the map (with lat/lng in the request body).
MAP_LOCATION_CONFIRM_TOKEN = "__AINETA_MAP_CONFIRM__"


class AINetaBot:
    """Main chatbot class with photo support"""
    
    def __init__(self, api_key: str):
        """Initialize the bot with Groq API key"""
        self.api_key = api_key  # Store for direct HTTP calls
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.3-70b-versatile"

        # Per-user state for multi-user concurrency
        self.conversation_history: Dict[str, list[Dict[str, str]]] = {}
        self.active_complaints: Dict[str, ComplaintData] = {}
        self.waiting_for_confirmation: Dict[str, bool] = {}
        self.waiting_for_photo: Dict[str, bool] = {}
        self.temp_complaints: Dict[str, ComplaintData] = {}
        self.user_coordinates: Dict[str, Dict[str, float]] = {}
        self.user_language: Dict[str, str] = {}  # Track user's language preference
        
        # Create photos directory if it doesn't exist
        if not os.path.exists('photos'):
            os.makedirs('photos')
        if not os.path.exists('uploads'):
            os.makedirs('uploads')
        
        # Conversational system prompt (avoid rigid robotic flow)
        self.system_prompt = """आप AI नेता हैं - एक conversational, natural और मददगार assistant.

Core behavior:
1) अगर user सामान्य बात कर रहा है, तो बिल्कुल normal chat करें (robotic 1-by-1 form mode में मत जाएं).
2) अगर user कोई civic समस्या/शिकायत बताता है, तो politely पूछें कि क्या वह formal complaint दर्ज करना चाहता/चाहती है.
3) Complaint flow में भी natural रहें: user के message से information समझें; missing info पर ही targeted follow-up पूछें.
4) Tone human, short, clear और context-aware रखें.

Critical language rule:
- Hinglish/Hindi/English को natural रूप से समझें.
- English words को over-analyze, गलत translate या incorrectly transliterate न करें.
- user intent और wording को faithfully preserve करें.
- उदाहरण: "whether" को "weather" न समझें; "gone" को "gaye" में distort न करें.
"""

        self.extraction_system_prompt = """You extract civic complaint details from conversational Hindi/English/Hinglish text.

Be literal and intent-faithful:
- Do NOT over-correct, over-translate, or hallucinate meanings.
- Do NOT confuse similar-looking words/intent (e.g., whether vs weather).
- Preserve user semantics; treat Hinglish naturally.

Extract fields:
- issue_type
- description
- location

issue_type routing (use short English keywords when possible):
- Prefer one of: road, water, electricity, sanitation, health — when the problem clearly fits.
- If the problem is unclear, mixed, or does not match those categories, set issue_type to exactly: default

Rules:
- If a field is missing, return null.
- Return STRICT JSON only with keys: issue_type, description, location.
"""
    
    def _detect_user_language(self, text: str) -> str:
        """Detect if user is writing in Hindi, English, or Hinglish"""
        # Check for Devanagari script (Hindi)
        if re.search(r'[\u0900-\u097F]', text):
            # If it has Hindi characters, it's Hindi or Hinglish
            # Check if it also has English words
            english_words = len(re.findall(r'[a-zA-Z]+', text))
            if english_words > 0 and len(text) > 10:
                return "hinglish"
            return "hindi"
        else:
            # No Hindi characters, assume English
            return "english"
    
    def process_message(self, user_message: str, user_id: str = "anonymous", phone: str = None) -> Dict[str, Any]:
        """Process user message and return response"""
        
        # Detect and store user's language
        detected_lang = self._detect_user_language(user_message)
        self.user_language[user_id] = detected_lang
        print(f"🔍 [DEBUG] Detected language for user {user_id}: {detected_lang}")
        
        # Add to per-user conversation history
        history = self.conversation_history.setdefault(user_id, [])
        history.append({"role": "user", "content": user_message})
        
        # Snapshot current per-user state
        user_complaint = self.active_complaints.get(user_id)
        waiting_photo = self.waiting_for_photo.get(user_id, False)
        waiting_conf = self.waiting_for_confirmation.get(user_id, False)
        
        # DEBUG: Print current state
        print(
            f"\n🔍 [DEBUG] State (user={user_id}) - "
            f"complaint: {user_complaint is not None}, "
            f"waiting_photo: {waiting_photo}, "
            f"waiting_conf: {waiting_conf}"
        )
        
        # 1. FIRST - Check for confirmation (HIGHEST PRIORITY)
        if waiting_conf:
            print("🔍 [DEBUG] Waiting for confirmation")
            cleaned_msg = user_message.lower().strip(" \t\n\r\\.,!?'\"")

            positive_keywords = ["yes", "yep", "sure", "haan", "ha", "ji", "ok", "हां", "हाँ", "जी", "bilkul"]
            negative_keywords = ["no", "nope", "nahi", "nahin", "cancel", "मत", "नहीं", "skip"]

            # If user clearly confirms → register complaint
            if any(word in cleaned_msg for word in positive_keywords):
                complaint_to_save = self.active_complaints.get(user_id)
                self._reset_user_state(user_id)
                print("🔍 [DEBUG] User confirmed (fuzzy positive), generating JSON...")
                return self._generate_complaint_json(user_id, phone, complaint_to_save)

            # If user clearly denies → cancel complaint
            if any(word in cleaned_msg for word in negative_keywords):
                self._reset_user_state(user_id)
                responses = {
                    "hindi": "ठीक है, शिकायत रद्द कर दी गई।",
                    "english": "Okay, complaint cancelled.",
                    "hinglish": "Theek hai, complaint cancel kar di.",
                }
                reply = responses.get(detected_lang, responses["hindi"])
                history.append({"role": "assistant", "content": reply})
                return {"type": "chat", "reply": reply}

            # Ambiguous response → ask for clarification (do NOT cancel)
            responses = {
                "hindi": "कृपया स्पष्ट करें – क्या आप शिकायत दर्ज कराना चाहते हैं? (हां/नहीं)",
                "english": "Please confirm – do you want to register the complaint? (yes/no)",
                "hinglish": "Please clear karo – kya aap complaint register karwana chahte ho? (haan/na)",
            }
            reply = responses.get(detected_lang, responses["hindi"])
            history.append({"role": "assistant", "content": reply})
            return {"type": "chat", "reply": reply}
        
        # 2. THEN check for photo
        if waiting_photo:
            print("🔍 [DEBUG] Waiting for photo")
            return self._handle_photo_input(user_id, user_message)
        
        # 3. THEN check for complaint collection
        if user_complaint is not None:
            print(f"🔍 [DEBUG] In complaint collection mode, current question: {user_complaint.current_question}")
            return self._handle_complaint_collection(user_id, user_message)
        
        # 4. THEN check for "हां" to START complaint
        cleaned_msg = user_message.lower().strip(" \t\n\r\\.,!?'\"")
        yes_variants = ["yes", "ha", "haan", "yep", "y", "ji", "ok", "sure", "karo", "darj", "yeah", "हां", "हाँ", "हा"]
        if (any(word in cleaned_msg for word in yes_variants)
                and self._last_message_was_confirmation(user_id)):
            print("🔍 [DEBUG] Starting new complaint - USER SAID YES")
            complaint = ComplaintData()
            complaint.current_question = "issue_type"
            self.active_complaints[user_id] = complaint
            
            # Response in user's language
            responses = {
                "hindi": "ठीक है। कृपया समस्या का प्रकार बताएं (सफाई, सड़क, बिजली, पानी):",
                "english": "Okay. Please tell the type of problem (sanitation, road, electricity, water):",
                "hinglish": "Theek hai. Problem ka type batao (safai, sadak, bijli, pani):"
            }
            reply = responses.get(detected_lang, responses["hindi"])
            history.append({"role": "assistant", "content": reply})
            return {"type": "start_collection", "reply": reply}
        
        # 5. Check for complaint intent
        print(f"🔍 [DEBUG] Checking complaint intent for: {user_message[:30]}...")
        if is_complaint_intent(user_message):
            print("🔍 [DEBUG] ✓ Complaint intent detected!")
            # Response in user's language
            responses = {
                "hindi": "क्या आप इस समस्या की औपचारिक शिकायत दर्ज कराना चाहेंगे? (हां/नहीं)",
                "english": "Would you like to register a formal complaint about this? (yes/no)",
                "hinglish": "Kya aap is problem ki formal complaint register karwana chahenge? (haan/na)"
            }
            reply = responses.get(detected_lang, responses["hindi"])
            history.append({"role": "assistant", "content": reply})
            return {"type": "ask_confirmation", "reply": reply}
        else:
            print("🔍 [DEBUG] ✗ Not a complaint intent")
        
        # 6. Normal chat - LLM response that matches user's language
        print("🔍 [DEBUG] Normal chat mode")
        return self._get_normal_response(user_id, user_message)

    def set_user_coordinates(self, user_id: str, latitude: float, longitude: float) -> None:
        """Persist latest map coordinates for the user session."""
        self.user_coordinates[user_id] = {
            "latitude": float(latitude),
            "longitude": float(longitude),
        }
    
    def _get_normal_response(self, user_id: str, user_message: str) -> Dict[str, Any]:
        """Get normal LLM response with browser-like headers to avoid 403"""
        history = self.conversation_history.setdefault(user_id, [])
        
        # Add language instruction
        detected_lang = self.user_language.get(user_id, "hindi")
        lang_instruction = ""
        if detected_lang == "english":
            lang_instruction = " Respond in English only."
        elif detected_lang == "hinglish":
            lang_instruction = " Respond in Hinglish (mix of Hindi and English) - exactly like how a normal person in India would speak."
        else:
            lang_instruction = " केवल हिंदी में जवाब दें।"
        
        messages = [
            {"role": "system", "content": self.system_prompt + lang_instruction},
            *history[-10:],
            {"role": "user", "content": user_message}
        ]
        
        print(f"🔍 [DEBUG] Sending request to Groq with {len(messages)} messages")
        print(f"🔍 [DEBUG] Using model: {self.model}")
        
        try:
            # Make direct HTTP request with browser-like headers
            response = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Origin": "https://console.groq.com",
                    "Referer": "https://console.groq.com/"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 1024
                },
                timeout=30.0
            )
            
            print(f"🔍 [DEBUG] Response status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                reply = result["choices"][0]["message"]["content"]
                print(f"🔍 [DEBUG] Got reply: {reply[:50]}...")
                
                history.append({"role": "assistant", "content": reply})
                
                return {
                    "type": "chat",
                    "reply": reply
                }
            else:
                print(f"🔍 [DEBUG] Error response: {response.text}")
                error_msg = "Service temporarily unavailable. Please try again."
                if detected_lang == "hindi":
                    error_msg = "सेवा अस्थायी रूप से उपलब्ध नहीं है। कृपया पुनः प्रयास करें।"
                elif detected_lang == "hinglish":
                    error_msg = "Service filhal available nahi hai. Phirse try karo."
                return {
                    "type": "error",
                    "reply": error_msg
                }
        
        except httpx.TimeoutException:
            print("🔍 [DEBUG] Request timeout")
            error_msg = "Request timeout. Please try again."
            return {"type": "error", "reply": error_msg}
            
        except httpx.HTTPStatusError as e:
            print(f"🔍 [DEBUG] HTTP Error: {e.response.status_code}")
            print(f"🔍 [DEBUG] Response: {e.response.text}")
            error_msg = "Service error. Please try again."
            return {"type": "error", "reply": error_msg}
            
        except Exception as e:
            print(f"🔍 [DEBUG] Exception: {type(e).__name__}: {e}")
            error_msg = "Sorry, technical error. Please try again."
            if detected_lang == "hindi":
                error_msg = "क्षमा करें, तकनीकी दिक्कत हुई। कृपया फिर से कोशिश करें।"
            elif detected_lang == "hinglish":
                error_msg = "Sorry, technical problem hui. Phirse try karo."
            return {
                "type": "error",
                "reply": error_msg,
                "error": str(e)
            }
    
    def _handle_photo_input(self, user_id: str, user_message: str) -> Dict[str, Any]:
        """Handle photo path input from user"""
        detected_lang = self.user_language.get(user_id, "hindi")
        
        # Normalize the message for comparison (robust cleaning)
        cleaned_msg = user_message.lower().strip(" \t\n\r\\.,!?'\"")
        
        # Check for "no" responses FIRST
        no_variants = ["no", "nahi", "na", "skip", "n", "नहीं", "ना"]
        if any(word in cleaned_msg for word in no_variants):
            # User doesn't want photo
            print("🔍 [DEBUG] User said NO to photo")
            self.waiting_for_photo[user_id] = False
            self.waiting_for_confirmation[user_id] = True
            if user_id in self.temp_complaints:
                complaint = self.temp_complaints.pop(user_id)
                complaint.photo_available = False
                complaint.photo_path = None
                self.active_complaints[user_id] = complaint
            return self._show_summary(user_id)
        
        # Check for "yes" responses
        yes_variants = ["yes", "ha", "haan", "yep", "y", "ji", "ok", "sure", "karo", "darj", "yeah", "हां", "हाँ", "हा"]
        if any(word in cleaned_msg for word in yes_variants):
            # User wants to send photo
            print("🔍 [DEBUG] User said YES to photo")
            responses = {
                "hindi": "कृपया फोटो की पूरी path दें (जैसे: C:\\photos\\problem.jpg):",
                "english": "Please provide the full photo path (e.g., C:\\photos\\problem.jpg):",
                "hinglish": "Photo ka full path do (jaise: C:\\photos\\problem.jpg):"
            }
            reply = responses.get(detected_lang, responses["hindi"])
            self.conversation_history.setdefault(user_id, []).append({"role": "assistant", "content": reply})
            return {
                "type": "question",
                "reply": reply,
                "field": "photo_path"
            }
        
        else:
            # This might be a photo path
            photo_path = user_message.strip().strip('"').strip("'")
            
            if os.path.exists(photo_path):
                # Save photo
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"photos/complaint_{timestamp}_{os.path.basename(photo_path)}"
                
                try:
                    shutil.copy2(photo_path, filename)
                    self.waiting_for_photo[user_id] = False
                    if user_id in self.temp_complaints:
                        complaint = self.temp_complaints.pop(user_id)
                        complaint.photo_available = True
                        complaint.photo_path = filename
                        self.active_complaints[user_id] = complaint
                    
                    responses = {
                        "hindi": "📸 फोटो सफलतापूर्वक सेव हो गई। धन्यवाद!",
                        "english": "📸 Photo saved successfully. Thank you!",
                        "hinglish": "📸 Photo successfully save ho gayi. Dhanyavaad!"
                    }
                    reply = responses.get(detected_lang, responses["hindi"])
                    self.conversation_history.setdefault(user_id, []).append({"role": "assistant", "content": reply})
                    return self._show_summary(user_id)
                except Exception as e:
                    responses = {
                        "hindi": f"फोटो सेव करने में समस्या हुई। कृपया फिर से path दें:",
                        "english": f"Error saving photo. Please provide the path again:",
                        "hinglish": f"Photo save karne mein problem hui. Phir se path do:"
                    }
                    reply = responses.get(detected_lang, responses["hindi"])
                    self.conversation_history.setdefault(user_id, []).append({"role": "assistant", "content": reply})
                    return {
                        "type": "question",
                        "reply": reply,
                        "field": "photo_path"
                    }
            else:
                # Not a valid path, and not yes/no - treat as invalid response
                responses = {
                    "hindi": "❌ यह सही जवाब नहीं है। कृपया हां या नहीं में जवाब दें:",
                    "english": "❌ That's not a valid response. Please answer yes or no:",
                    "hinglish": "❌ Yeh sahi jawab nahi hai. Haan ya na mein jawab do:"
                }
                reply = responses.get(detected_lang, responses["hindi"])
                self.conversation_history.setdefault(user_id, []).append({"role": "assistant", "content": reply})
                return {
                    "type": "question",
                    "reply": reply,
                    "field": "photo_consent"
                }

    def save_uploaded_photo(
        self,
        user_id: str,
        file_bytes: bytes,
        original_filename: Optional[str],
        content_type: Optional[str],
    ) -> Dict[str, Any]:
        """
        Save a browser-uploaded image when user is at the photo consent step.
        Writes under uploads/, updates complaint state, returns complaint_summary like the text flow.
        """
        detected_lang = self.user_language.get(user_id, "hindi")

        if not self.waiting_for_photo.get(user_id, False):
            responses = {
                "hindi": "अभी फोटो अपलोड की अनुमति नहीं है। कृपया पहले बॉट के निर्देशों का पालन करें।",
                "english": "Photo upload is not available right now. Please follow the bot flow first.",
                "hinglish": "Abhi photo upload allowed nahi hai. Pehle bot flow follow karo.",
            }
            return {
                "type": "error",
                "reply": responses.get(detected_lang, responses["hindi"]),
                "error": "not_waiting_photo",
            }

        if user_id not in self.temp_complaints:
            responses = {
                "hindi": "कोई लंबित शिकायत नहीं मिली। कृपया फिर से शुरू करें।",
                "english": "No pending complaint found. Please start again.",
                "hinglish": "Pending complaint nahi mili. Phirse shuru karo.",
            }
            return {
                "type": "error",
                "reply": responses.get(detected_lang, responses["hindi"]),
                "error": "no_pending_complaint",
            }

        allowed_mimes = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }
        ct = (content_type or "").split(";")[0].strip().lower()
        ext = allowed_mimes.get(ct)

        if not ext and original_filename:
            lower = original_filename.lower()
            for candidate in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                if lower.endswith(candidate):
                    ext = ".jpg" if candidate == ".jpeg" else candidate
                    break

        if not ext:
            responses = {
                "hindi": "कृपया केवल JPG, PNG, WebP या GIF छवि अपलोड करें।",
                "english": "Please upload only a JPG, PNG, WebP, or GIF image.",
                "hinglish": "Sirf JPG/PNG/WebP/GIF image upload karo.",
            }
            return {
                "type": "error",
                "reply": responses.get(detected_lang, responses["hindi"]),
                "error": "invalid_image_type",
            }

        max_bytes = 8 * 1024 * 1024
        if len(file_bytes) > max_bytes:
            responses = {
                "hindi": "फ़ाइल बहुत बड़ी है (अधिकतम 8 MB)।",
                "english": "File is too large (max 8 MB).",
                "hinglish": "File bahut badi hai (max 8 MB).",
            }
            return {
                "type": "error",
                "reply": responses.get(detected_lang, responses["hindi"]),
                "error": "file_too_large",
            }

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = f"uploads/complaint_{timestamp}_{uuid.uuid4().hex[:12]}{ext}"
        try:
            with open(safe_name, "wb") as out:
                out.write(file_bytes)
        except OSError as e:
            print(f"🔍 [DEBUG] Failed to save upload: {e}")
            responses = {
                "hindi": "फोटो सेव नहीं हो सकी। कृपया पुनः प्रयास करें।",
                "english": "Could not save the photo. Please try again.",
                "hinglish": "Photo save nahi ho payi. Phirse try karo.",
            }
            return {
                "type": "error",
                "reply": responses.get(detected_lang, responses["hindi"]),
                "error": "save_failed",
            }

        self.waiting_for_photo[user_id] = False
        self.waiting_for_confirmation[user_id] = True
        complaint = self.temp_complaints.pop(user_id)
        complaint.photo_available = True
        complaint.photo_path = safe_name
        self.active_complaints[user_id] = complaint

        responses_saved = {
            "hindi": "📸 फोटो सफलतापूर्वक सेव हो गई। धन्यवाद!",
            "english": "📸 Photo saved successfully. Thank you!",
            "hinglish": "📸 Photo successfully save ho gayi. Dhanyavaad!",
        }
        reply_saved = responses_saved.get(detected_lang, responses_saved["hindi"])
        self.conversation_history.setdefault(user_id, []).append(
            {"role": "assistant", "content": reply_saved}
        )

        return self._show_summary(user_id)

    def _reverse_geocode_osm(self, lat: float, lng: float) -> Optional[str]:
        """Resolve coordinates to a human-readable address via OpenStreetMap Nominatim (free)."""
        try:
            r = httpx.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lng, "format": "json"},
                headers={
                    "User-Agent": "AINETA-Shivpuri-CivicBot/1.0 (https://github.com/local; contact: civic@local)",
                    "Accept-Language": "en,hi",
                },
                timeout=10.0,
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("display_name")
        except Exception as e:
            print(f"🔍 [DEBUG] Nominatim reverse geocode error: {e}")
        return None

    def _apply_map_pin_to_complaint(self, user_id: str, complaint: ComplaintData) -> bool:
        """Fill location from latest pinned coordinates + OSM reverse geocode."""
        coord = self.user_coordinates.get(user_id)
        if not coord:
            return False
        lat = float(coord["latitude"])
        lng = float(coord["longitude"])
        complaint.latitude = lat
        complaint.longitude = lng
        label = self._reverse_geocode_osm(lat, lng)
        if label:
            complaint.location = label[:500]
        else:
            complaint.location = f"Map pin — {lat:.5f}, {lng:.5f} (Shivpuri area)"
        complaint.current_question = "location"
        return True

    def _transition_to_photo_step(self, user_id: str, complaint: ComplaintData, detected_lang: str) -> Dict[str, Any]:
        """Issue type, description, and location are complete — ask for photo consent."""
        print("🔍 [DEBUG] All fields collected, moving to photo step")
        self.waiting_for_photo[user_id] = True
        self.temp_complaints[user_id] = complaint
        self.active_complaints.pop(user_id, None)

        collected = complaint.to_dict()
        responses = {
            "hindi": "क्या आप समस्या की फोटो भेजना चाहेंगे? (हां/नहीं):",
            "english": "Would you like to send a photo of the problem? (yes/no):",
            "hinglish": "Kya aap problem ki photo bhejna chahenge? (haan/na):",
        }
        reply = responses.get(detected_lang, responses["hindi"])
        self.conversation_history.setdefault(user_id, []).append(
            {"role": "assistant", "content": reply}
        )
        return {
            "type": "question",
            "reply": reply,
            "field": "photo_consent",
            "collected_so_far": collected,
        }

    def _handle_complaint_collection(self, user_id: str, user_message: str) -> Dict[str, Any]:
        """Handle complaint collection flow using LLM JSON extraction."""
        detected_lang = self.user_language.get(user_id, "hindi")

        complaint = self.active_complaints.get(user_id)
        if not complaint:
            responses = {
                "hindi": "मुझे शिकायत का डेटा नहीं मिला। कृपया फिर से शुरू करें।",
                "english": "I couldn't find complaint data. Please start again.",
                "hinglish": "Mujhe complaint ka data nahi mila. Phirse shuru karo."
            }
            reply = responses.get(detected_lang, responses["hindi"])
            self.conversation_history.setdefault(user_id, []).append(
                {"role": "assistant", "content": reply}
            )
            return {"type": "error", "reply": reply}

        print(f"🔍 [DEBUG] Handling complaint collection (user={user_id}) with LLM extraction")
        print(f"🔍 [DEBUG] Current complaint data: {complaint.to_dict()}")

        # Map-first location (Zomato-style): user taps "Confirm Location" on the OSM map in the app.
        msg_stripped = user_message.strip()
        is_map_confirm = (
            msg_stripped == MAP_LOCATION_CONFIRM_TOKEN
            or msg_stripped.startswith("📍 Location confirmed")
        )
        if (
            complaint.issue_type
            and complaint.description
            and not complaint.location
            and is_map_confirm
        ):
            if self._apply_map_pin_to_complaint(user_id, complaint):
                return self._transition_to_photo_step(user_id, complaint, detected_lang)
            responses_err = {
                "hindi": "कृपया नक्शे पर पिन लगाकर Confirm Location दबाएं। खोज से जगह मिले तो पिन वहीं रखें।",
                "english": "Please drop the pin on the map and tap Confirm Location. Use search to find your area first if needed.",
                "hinglish": "Map par pin lagao aur Confirm Location dabao. Pehle search se area dhundh sakte ho.",
            }
            reply_err = responses_err.get(detected_lang, responses_err["hindi"])
            self.conversation_history.setdefault(user_id, []).append(
                {"role": "assistant", "content": reply_err}
            )
            return {
                "type": "question",
                "reply": reply_err,
                "field": "location",
                "collected_so_far": complaint.to_dict(),
            }

        extracted: Dict[str, Any] = {}

        # Only call Groq if we actually need extraction
        needs_extraction = False
        missing_fields = []
        
        if not complaint.issue_type:
            missing_fields.append("issue_type")
            needs_extraction = True
        if not complaint.description:
            missing_fields.append("description") 
            needs_extraction = True
        if not complaint.location:
            missing_fields.append("location")
            needs_extraction = True

        # Map confirm token has no natural language for the LLM to extract
        if needs_extraction and msg_stripped == MAP_LOCATION_CONFIRM_TOKEN:
            needs_extraction = False

        if needs_extraction:
            # Call Groq in JSON mode to extract complaint fields
            try:
                # Create a focused prompt based on what we need
                extraction_prompt = f"""Extract complaint details from this message: "{user_message}"

Current known information:
- issue_type: {complaint.issue_type or 'unknown'}
- description: {complaint.description or 'unknown'}
- location: {complaint.location or 'unknown'}

We need to find: {', '.join(missing_fields)}

Return ONLY a JSON object with these fields (use null if not found):
{{
  "issue_type": "...",
  "description": "...", 
  "location": "..."
}}"""

                # Make direct HTTP request for extraction
                response = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": self.extraction_system_prompt},
                            {"role": "user", "content": extraction_prompt},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.1,
                        "max_tokens": 256,
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    raw_content = result["choices"][0]["message"]["content"]
                    print(f"🔍 [DEBUG] Extraction raw JSON (user={user_id}): {raw_content}")
                    
                    if raw_content and raw_content.strip():
                        extracted = json.loads(raw_content)
                else:
                    print(f"🔍 [DEBUG] Extraction error: {response.status_code}")
                    
            except json.JSONDecodeError as e:
                print(f"🔍 [DEBUG] JSON decode error: {e}")
                # Try to extract JSON from the response if it's wrapped in text
                json_match = re.search(r'\{.*\}', raw_content, re.DOTALL) if raw_content else None
                if json_match:
                    try:
                        extracted = json.loads(json_match.group())
                    except:
                        extracted = {}
            except Exception as e:
                print(f"🔍 [DEBUG] Extraction error (user={user_id}): {e}")
                extracted = {}

            # Merge extracted data into existing complaint (only fill missing fields)
            for field in ("issue_type", "description", "location"):
                current_value = getattr(complaint, field, None)
                new_value = extracted.get(field)
                if current_value is None and new_value not in (None, "", "null"):
                    setattr(complaint, field, new_value)
                    print(f"🔍 [DEBUG] Set {field} to: {new_value}")

        collected = complaint.to_dict()
        print(f"🔍 [DEBUG] Collected so far: {collected}")

        # Determine which fields are still missing, in priority order
        if not complaint.issue_type:
            responses = {
                "hindi": "कृपया समस्या का प्रकार बताएं (जैसे: सफाई, सड़क, बिजली, पानी):",
                "english": "Please tell the type of problem (sanitation, road, electricity, water):",
                "hinglish": "Problem ka type batao (jaise: safai, sadak, bijli, pani):"
            }
            reply = responses.get(detected_lang, responses["hindi"])
            complaint.current_question = "issue_type"
            self.conversation_history.setdefault(user_id, []).append(
                {"role": "assistant", "content": reply}
            )
            return {
                "type": "question",
                "reply": reply,
                "field": "issue_type",
                "collected_so_far": collected,
            }

        if not complaint.description:
            responses = {
                "hindi": "कृपया समस्या का विस्तृत विवरण दें:",
                "english": "Please provide a detailed description of the problem:",
                "hinglish": "Problem ka detailed description do:"
            }
            reply = responses.get(detected_lang, responses["hindi"])
            complaint.current_question = "description"
            self.conversation_history.setdefault(user_id, []).append(
                {"role": "assistant", "content": reply}
            )
            return {
                "type": "question",
                "reply": reply,
                "field": "description",
                "collected_so_far": collected,
            }

        if not complaint.location:
            responses = {
                "hindi": "📍 नक्शे पर सही जगह चुनें (Zomato जैसा) — ऊपर search से society/गली ढूंढें, pin खींचें, फिर Confirm Location दबाएं। वैकल्पिक: यहाँ टाइप करके मोहल्ला/वार्ड भी लिख सकते हैं।",
                "english": "📍 Pick the exact spot on the map — use the search bar (OpenStreetMap) to find your society or street, drag the pin, then tap Confirm Location. Or type the area/ward here if you prefer.",
                "hinglish": "📍 Map par exact spot choose karo — upar search se society/street dhundo (OpenStreetMap), pin drag karo, phir Confirm Location dabao. Ya yahan type karke mohalla/ward bhi bata sakte ho.",
            }
            reply = responses.get(detected_lang, responses["hindi"])
            complaint.current_question = "location"
            self.conversation_history.setdefault(user_id, []).append(
                {"role": "assistant", "content": reply}
            )
            return {
                "type": "question",
                "reply": reply,
                "field": "location",
                "collected_so_far": collected,
            }

        return self._transition_to_photo_step(user_id, complaint, detected_lang)
    
    def _show_summary(self, user_id: str) -> Dict[str, Any]:
        """Show complaint summary"""
        print(f"🔍 [DEBUG] Showing summary for user {user_id}")
        self.waiting_for_photo[user_id] = False
        self.waiting_for_confirmation[user_id] = True
        
        # Restore complaint from temp if needed
        if user_id in self.temp_complaints and user_id not in self.active_complaints:
            self.active_complaints[user_id] = self.temp_complaints.pop(user_id)
            print(f"🔍 [DEBUG] Restored complaint from temp")
        
        complaint = self.active_complaints.get(user_id)
        if not complaint:
            print(f"🔍 [DEBUG] ERROR: No complaint to show summary for user {user_id}")
            # Try to recover
            if user_id in self.temp_complaints:
                self.active_complaints[user_id] = self.temp_complaints.pop(user_id)
                complaint = self.active_complaints.get(user_id)
        
        reply = self._get_complaint_summary(user_id)
        self.conversation_history.setdefault(user_id, []).append({"role": "assistant", "content": reply})

        return {
            "type": "complaint_summary",
            "reply": reply,
            "summary_data": complaint.to_dict() if complaint else {}
        }
    
    def _get_complaint_summary(self, user_id: str) -> str:
        """Generate complaint summary for user confirmation"""
        complaint = self.active_complaints.get(user_id)
        detected_lang = self.user_language.get(user_id, "hindi")
        
        if not complaint:
            return "कोई शिकायत डेटा नहीं है।"
        
        # Summary in user's language
        if detected_lang == "english":
            summary = f"""📋 Your Complaint Summary:

Problem Type: {complaint.issue_type}
Description: {complaint.description}
Location: {complaint.location}"""
        elif detected_lang == "hinglish":
            summary = f"""📋 Aapki Complaint ka Summary:

Problem Type: {complaint.issue_type}
Description: {complaint.description}
Location: {complaint.location}"""
        else:  # hindi
            summary = f"""📋 आपकी शिकायत का सारांश:

समस्या का प्रकार: {complaint.issue_type}
विवरण: {complaint.description}
स्थान: {complaint.location}"""
        
        if hasattr(complaint, 'photo_available') and complaint.photo_available:
            if detected_lang == "english":
                summary += f"\nPhoto: ✅ (Saved)"
            elif detected_lang == "hinglish":
                summary += f"\nPhoto: ✅ (Save ho gayi)"
            else:
                summary += f"\nफोटो: ✅ (सेव हो गई)"
        else:
            if detected_lang == "english":
                summary += f"\nPhoto: ❌ No"
            elif detected_lang == "hinglish":
                summary += f"\nPhoto: ❌ Nahi"
            else:
                summary += f"\nफोटो: ❌ नहीं"
        
        if detected_lang == "english":
            summary += "\n\nIs this information correct? Do you want to register the complaint? (yes/no)"
        elif detected_lang == "hinglish":
            summary += "\n\nKya yeh information sahi hai? Kya aap complaint register karwana chahte hain? (haan/na)"
        else:
            summary += "\n\nक्या यह जानकारी सही है? क्या आप शिकायत दर्ज कराना चाहते हैं? (हां/नहीं)"
        
        return summary
    
    def _generate_complaint_json(self, user_id: str, phone: str, complaint_data: Optional[ComplaintData] = None) -> Dict[str, Any]:
        """Generate final JSON for backend"""
        
        print("🔍 [DEBUG] ===== GENERATING COMPLAINT JSON =====")
        print(f"🔍 [DEBUG] User ID: {user_id}")
        print(f"🔍 [DEBUG] Phone: {phone}")
        print(f"🔍 [DEBUG] Complaint data provided: {complaint_data is not None}")
        
        # Use provided complaint data or fall back to per-user active complaint
        complaint = complaint_data if complaint_data else self.active_complaints.get(user_id)
        
        if not complaint:
            print("🔍 [DEBUG] ERROR: No complaint data to generate JSON!")
            # Try to recover from temp
            if user_id in self.temp_complaints:
                complaint = self.temp_complaints.get(user_id)
                print("🔍 [DEBUG] Recovered complaint from temp")
            else:
                return {
                    "type": "error",
                    "reply": "कोई शिकायत डेटा नहीं मिला।",
                    "json": None
                }
        
        print(f"🔍 [DEBUG] Complaint data: {complaint.to_dict()}")
        
        # Generate complaint ID
        complaint_id = f"NETA-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
        print(f"🔍 [DEBUG] Generated complaint ID: {complaint_id}")
        
        # Get department
        department = assign_department(complaint.issue_type if complaint else "")
        print(f"🔍 [DEBUG] Assigned department: {department}")
        coord = self.user_coordinates.get(user_id, {})
        
        # Create JSON
        complaint_json = {
            "complaint_id": complaint_id,
            "user": {
                "user_id": user_id,
                "phone": phone
            },
            "complaint_data": {
                "issue_type": complaint.issue_type if complaint else "",
                "description": complaint.description if complaint else "",
                "location": complaint.location if complaint else "",
                "ward": getattr(complaint, 'ward', None) if complaint else None,
                "landmark": getattr(complaint, 'landmark', None) if complaint else None,
                "latitude": coord.get("latitude"),
                "longitude": coord.get("longitude"),
                "photo_available": getattr(complaint, 'photo_available', False) if complaint else False,
                "photo_path": getattr(complaint, 'photo_path', None) if complaint else None
            },
            "metadata": {
                "submitted_at": datetime.now().isoformat(),
                "language": self.user_language.get(user_id, "hindi")
            },
            "department": department,
            "status": {
                "current": "submitted",
                "submitted_at": datetime.now().isoformat()
            }
        }
        
        print(f"🔍 [DEBUG] JSON created successfully")
        
        # Create the wrapped version for saving
        wrapped_json = {"complaint": complaint_json}
        
        # Reset all state for this user
        self._reset_user_state(user_id)
        
        print(f"🔍 [DEBUG] ===== JSON GENERATION COMPLETE =====\n")
        
        # Success message in user's language
        detected_lang = self.user_language.get(user_id, "hindi")
        if detected_lang == "english":
            reply = f"✅ Your complaint has been registered!\n\nComplaint ID: {complaint_id}\nDepartment: {department['name']}"
        elif detected_lang == "hinglish":
            reply = f"✅ Aapki complaint register ho gayi!\n\nComplaint ID: {complaint_id}\nDepartment: {department['name']}"
        else:
            reply = f"✅ आपकी शिकायत दर्ज हो गई है!\n\nशिकायत ID: {complaint_id}\nविभाग: {department['name']}"
        
        return {
            "type": "complaint_registered",
            "reply": reply,
            "json": wrapped_json
        }
    
    def _reset_user_state(self, user_id: str) -> None:
        """Clear all in-memory state for a specific user."""
        self.active_complaints.pop(user_id, None)
        self.temp_complaints.pop(user_id, None)
        self.waiting_for_photo.pop(user_id, None)
        self.waiting_for_confirmation.pop(user_id, None)
        self.user_coordinates.pop(user_id, None)
        # Don't reset language preference
    
    def _last_message_was_confirmation(self, user_id: str) -> bool:
        """Check if last bot message was asking for confirmation"""
        history = self.conversation_history.get(user_id, [])
        if len(history) < 2:
            return False
        
        # Get the last assistant message
        for msg in reversed(history):
            if msg["role"] == "assistant":
                last_msg = msg["content"]
                print(f"🔍 [DEBUG] Last assistant message: {last_msg[:50]}...")
                # Check if it was asking about complaint registration
                return "औपचारिक शिकायत दर्ज कराना चाहेंगे" in last_msg or "शिकायत दर्ज कराना चाहेंगे" in last_msg or "formal complaint" in last_msg.lower()
        return False