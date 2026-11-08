from django.urls import path
from django.views.generic import RedirectView
from support.admin import site

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="admin:index")),
    path("admin/", site.urls),
]
