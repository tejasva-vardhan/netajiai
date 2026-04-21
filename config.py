# config.py
"""
AI NETA - Configuration
Loads environment variables and settings
"""

import os
from dotenv import load_dotenv
from typing import Dict

def load_config() -> Dict[str, str]:
    """Load configuration from .env file"""
    load_dotenv()
    
    return {
        'GROQ_API_KEY': os.getenv('GROQ_API_KEY', ''),
        'MODEL_NAME': os.getenv('MODEL_NAME', "llama-3.3-70b-versatile")   }