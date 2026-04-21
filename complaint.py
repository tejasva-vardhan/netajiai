 # complaint.py
"""
AI NETA - Complaint Data Model with Photo Support
"""

from typing import Optional, Dict, List

class ComplaintData:
    """Complaint data model with photo support"""
    
    def __init__(self):
        self.issue_type: Optional[str] = None
        self.description: Optional[str] = None
        self.location: Optional[str] = None
        self.ward: Optional[str] = None
        self.landmark: Optional[str] = None
        self.latitude: Optional[float] = None
        self.longitude: Optional[float] = None
        self.photo_available: bool = False
        self.photo_path: Optional[str] = None  # New field for photo path
        self.current_question: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "issue_type": self.issue_type,
            "description": self.description,
            "location": self.location,
            "ward": self.ward,
            "landmark": self.landmark,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "photo_available": self.photo_available,
            "photo_path": self.photo_path
        }
    
    def is_complete(self) -> bool:
        """Check if all required fields are collected"""
        return all([
            self.issue_type is not None,
            self.description is not None,
            self.location is not None
        ])
    
    def get_next_question(self) -> Optional[Dict[str, str]]:
        """Get the next question to ask"""
        if not self.issue_type:
            return {
                "question": "कृपया समस्या का प्रकार बताएं (जैसे: सफाई, सड़क, बिजली, पानी, आदि):",
                "field": "issue_type"
            }
        elif not self.description:
            return {
                "question": "कृपया समस्या का विस्तृत विवरण दें:",
                "field": "description"
            }
        elif not self.location:
            return {
                "question": "नक्शे पर pin लगाकर स्थान चुनें (search + Confirm), या मोहल्ला/वार्ड यहाँ लिखें:",
                "field": "location"
            }
        return None
    
    def get_missing_fields(self) -> List[str]:
        """Get list of missing fields"""
        missing = []
        if not self.issue_type:
            missing.append("समस्या का प्रकार")
        if not self.description:
            missing.append("विवरण")
        if not self.location:
            missing.append("स्थान")
        return missing