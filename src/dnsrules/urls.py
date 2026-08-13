from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from dnsrules.core import views as core_views

urlpatterns = [
    path("", core_views.dashboard, name="dashboard"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
]
