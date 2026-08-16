from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import CRMLoginView, UserCreateView, user_edit, user_list


app_name = "accounts"

urlpatterns = [
    path("login/", CRMLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("users/", user_list, name="user-list"),
    path("users/create/", UserCreateView.as_view(), name="user-create"),
    path("users/<int:pk>/", user_edit, name="user-edit"),
]
