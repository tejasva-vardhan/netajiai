"""Server-owned issue categories used by citizen-facing intake surfaces."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IssueCategory:
    code: str
    icon: str
    label_hi: str
    label_en: str
    spoken_hi: str


ISSUE_CATALOG_VERSION = "issue-catalog.v1"

# This is the controlled launch taxonomy, not a substitute for the later
# jurisdiction-owned policy catalogue. The API exposes this tuple so mobile
# and assisted surfaces do not invent their own category codes.
ISSUE_CATEGORIES: tuple[IssueCategory, ...] = (
    IssueCategory("road", "🛣️", "सड़क / गड्ढा", "Road / pothole", "सड़क और गड्ढे की समस्या"),
    IssueCategory("water", "🚰", "पानी", "Water", "पानी की समस्या"),
    IssueCategory("garbage", "🗑️", "कचरा", "Garbage", "कचरा नहीं उठ रहा"),
    IssueCategory("streetlight", "💡", "स्ट्रीट लाइट", "Streetlight", "स्ट्रीट लाइट की समस्या"),
    IssueCategory("drainage", "🌧️", "नाली / जलभराव", "Drainage / flooding", "नाली या जलभराव की समस्या"),
)


def get_issue_categories() -> tuple[IssueCategory, ...]:
    """Return the immutable launch catalogue for API projection."""

    return ISSUE_CATEGORIES
