"""CJ O-NE 배송조회 통합구성요소 상수."""

from datetime import timedelta

DOMAIN = "cj_one_delivery"

CONF_AUTH_CODE = "auth_code"
CONF_ACCESS_TOKEN = "access_token"
CONF_PHONE_NUMBER = "phone_number"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_USER_ID = "user_id"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=30)
ACTIVE_SLOT_LIMIT = 3
COMPLETED_RECENT_LIMIT = 5

PLATFORMS = ["sensor"]
