from .mock import MockAdapter
from .bigbasket import BigBasketAdapter

ADAPTERS = {"mock": MockAdapter, "bigbasket": BigBasketAdapter}
DEFAULT = MockAdapter  # swap per platform as real adapters land, e.g. ADAPTERS["bigbasket"] = BigBasketAdapter


def get_adapter(platform):
    return ADAPTERS.get(platform.lower(), DEFAULT)()


# What users can pick in the UI. needs_password: portal uses a password (BigBasket is email + OTP only).
PLATFORMS = [
    {"id": "bigbasket", "label": "BigBasket", "ready": True, "needs_password": False},
    {"id": "demo", "label": "Demo (practice mode)", "ready": True, "needs_password": False},
    {"id": "blinkit", "label": "Blinkit", "ready": False, "needs_password": False},
    {"id": "zepto", "label": "Zepto", "ready": False, "needs_password": False},
    {"id": "instamart", "label": "Swiggy Instamart", "ready": False, "needs_password": False},
]
ADAPTERS["demo"] = MockAdapter
