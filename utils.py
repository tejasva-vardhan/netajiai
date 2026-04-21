# utils.py
"""
AI NETA - Utility Functions
Helper functions for the chatbot
"""

from typing import Dict, List

def is_complaint_intent(message: str) -> bool:
    """Check if user message indicates a complaint"""
    keywords = [
        "शिकायत", "complaint", "problem", "दिक्कत", "समस्या",
        "कचरा", "सड़क", "बिजली", "पानी", "नाली", "गंदगी",
        "खराब", "टूटा", "बंद", "नहीं उठता", "नहीं आ रहा",
        "गिरा", "चोरी", "रोशनी", "अँधेरा", "जलभराव"
    ]
    
    message_lower = message.lower()
    return any(keyword in message_lower for keyword in keywords)

def assign_department(issue_type: str) -> Dict[str, str]:
    """Map issue type to department"""
    issue_lower = issue_type.lower() if issue_type else ""
    
    # Sanitation
    if any(word in issue_lower for word in ["सफाई", "कचरा", "गंदगी", "clean", "garbage"]):
        return {
            "name": "स्वच्छता विभाग",
            "code": "SAN",
            "email": "sanitation@shivpuri.nic.in"
        }
    
    # PWD/Roads
    elif any(word in issue_lower for word in ["सड़क", "पोथोल", "टूटा", "road", "pothole"]):
        return {
            "name": "लोक निर्माण विभाग",
            "code": "PWD",
            "email": "pwd@shivpuri.nic.in"
        }
    
    # Electricity
    elif any(word in issue_lower for word in ["बिजली", "लाइट", "बल्ब", "electricity", "light"]):
        return {
            "name": "विद्युत विभाग",
            "code": "ELEC",
            "email": "electricity@shivpuri.nic.in"
        }
    
    # Water
    elif any(word in issue_lower for word in ["पानी", "जल", "नल", "water"]):
        return {
            "name": "जल विभाग",
            "code": "WATER",
            "email": "water@shivpuri.nic.in"
        }
    
    # Default / unclassified — aligns with Department.keyword "default" in DB seed
    else:
        return {
            "name": "General / Unclassified",
            "code": "GEN",
            "email": "complaints@shivpuri.nic.in",
        }

def format_phone(phone: str) -> str:
    """Format phone number"""
    # Remove non-digits
    digits = ''.join(filter(str.isdigit, phone))
    
    # Format as Indian number
    if len(digits) == 10:
        return f"+91{digits}"
    elif len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    else:
        return phone
    

import re

def detect_language(text: str) -> str:
    """Detect if text is Hindi, English, or Hinglish"""
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