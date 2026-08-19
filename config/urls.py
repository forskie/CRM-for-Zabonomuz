from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path

from apps.core.views import dashboard


def healthcheck(_request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", dashboard, name="dashboard"),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.education.urls")),
    path("health/", healthcheck, name="healthcheck"),
]
