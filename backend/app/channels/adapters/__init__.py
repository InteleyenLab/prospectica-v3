"""Auto-registro de los 11 adaptadores colombianos/LATAM + adaptadores legado OASIS."""

from .advertising import AdvertisingAdapter
from .colombian_web import ColombianWebAdapter
from .facebook_groups import FacebookGroupsAdapter
from .focus_group import FocusGroupAdapter
from .instagram import InstagramAdapter
from .legacy_oasis import LegacyRedditAdapter, LegacyTwitterAdapter
from .news_portals import NewsPortalsAdapter
from .radio import RadioAdapter
from .street_survey import StreetSurveyAdapter
from .tiktok import TikTokAdapter
from .tv import TVAdapter
from .whatsapp_1on1 import WhatsApp1on1Adapter

__all__ = [
    "WhatsApp1on1Adapter",
    "FocusGroupAdapter",
    "StreetSurveyAdapter",
    "FacebookGroupsAdapter",
    "TikTokAdapter",
    "InstagramAdapter",
    "NewsPortalsAdapter",
    "ColombianWebAdapter",
    "AdvertisingAdapter",
    "TVAdapter",
    "RadioAdapter",
    "LegacyTwitterAdapter",
    "LegacyRedditAdapter",
]
