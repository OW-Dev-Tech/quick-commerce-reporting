from .mock import MockAdapter
from .bigbasket import BigBasketAdapter

ADAPTERS = {"mock": MockAdapter, "bigbasket": BigBasketAdapter}
DEFAULT = MockAdapter  # swap per platform as real adapters land, e.g. ADAPTERS["bigbasket"] = BigBasketAdapter


def get_adapter(platform):
    return ADAPTERS.get(platform.lower(), DEFAULT)()
