from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from dnsrules.core import views as core_views
from dnsrules.queries import views as queries_views
from dnsrules.rules import views as rules_views

urlpatterns = [
    path("", core_views.dashboard, name="dashboard"),
    path("rules/", rules_views.index, name="rules"),
    path("rules/<int:pk>/", rules_views.rule, name="rule"),
    path("queries/", queries_views.index, name="queries"),
    path("queries/rule/", queries_views.rule, name="queries.rule"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
]
