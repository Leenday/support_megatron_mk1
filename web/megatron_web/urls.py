from django.contrib import admin
from django.urls import include, path

from support import views

urlpatterns = [
    path("", views.request_form, name="request_form"),
    path("status/<int:pk>-<str:code>/", views.request_status, name="request_status"),
    path("i18n/", include("django.conf.urls.i18n")),  # set_language: the RU / EN switch
    path("admin/", admin.site.urls),
]
