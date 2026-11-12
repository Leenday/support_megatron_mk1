from django.contrib.auth import views as auth_views
from django.urls import include, path

from support import desk, views
from support.admin import site
from support.api import api
from support.forms import DeskLoginForm

urlpatterns = [
    path("", views.request_form, name="request_form"),
    path("status/<int:pk>-<str:code>/", views.request_status, name="request_status"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="support/login.html", authentication_form=DeskLoginForm, next_page="desk"
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("desk/", desk.queue, name="desk"),  # the specialist's dashboard (#18)
    path("desk/tickets/<int:pk>/", desk.ticket_page, name="desk_ticket"),
    path("desk/tickets/<int:pk>/<str:action>/", desk.act, name="desk_action"),
    path("i18n/", include("django.conf.urls.i18n")),  # set_language: the RU / EN switch
    path("api/", api.urls),  # Swagger UI at /api/docs, schema at /api/openapi.json (#42)
    path("admin/", site.urls),
]
