from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("analytics/", views.analytics_view, name="analytics"),
]
