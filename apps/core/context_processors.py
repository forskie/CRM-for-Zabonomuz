import re

from django.conf import settings


def center_contact(_request):
    phone = settings.CENTER_PHONE
    digits = re.sub(r"\D", "", phone)
    return {
        "center_phone": phone,
        "center_phone_href": f"+{digits}" if phone.startswith("+") else digits,
        "center_address": settings.CENTER_ADDRESS,
    }
