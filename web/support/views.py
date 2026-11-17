"""Pages for requesters (#17): an open form and a status page behind a secret link.

Requesters have no account, so the status link carries a random code: request numbers are
consecutive and would otherwise let anyone read other people's requests.
"""

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.utils.translation import get_language

from support.forms import RequestForm
from support.models import Request, User
from support.services import create_ticket


def status_url(saved: Request) -> str:
    return reverse("request_status", kwargs={"pk": saved.pk, "code": saved.access_code})


def within_rate_limit(request: HttpRequest) -> bool:
    """At most REQUEST_FORM_RATE = (requests, seconds) submissions per client address.

    REMOTE_ADDR is the direct client; behind a reverse proxy it would be the proxy's.
    """
    limit, seconds = settings.REQUEST_FORM_RATE
    key = f"request-form:{request.META.get('REMOTE_ADDR', '')}"
    cache.add(key, 0, timeout=seconds)
    return cache.incr(key) <= limit


def request_form(request: HttpRequest) -> HttpResponse:
    form = RequestForm(request.POST or None)
    if request.method == "POST":
        if not within_rate_limit(request):
            context = {"form": form, "rate_limited": True}
            return render(request, "support/request_form.html", context, status=429)
        if form.is_valid():
            saved = create_ticket(
                form.cleaned_data["text"],
                form.cleaned_data["contact"],
                # Requesters need no account; a logged-in employee is kept as the requester.
                requester=request.user if isinstance(request.user, User) else None,
            )
            # Redirect after POST, so reloading the result page does not send it again.
            return redirect(status_url(saved) + "?new=1")
    return render(request, "support/request_form.html", {"form": form})


def request_status(request: HttpRequest, pk: int, code: str) -> HttpResponse:
    saved = get_object_or_404(Request.objects.prefetch_related("tickets__department"), pk=pk)
    if not constant_time_compare(code, saved.access_code):
        raise Http404
    language = get_language() or settings.LANGUAGE_CODE
    tickets = [(t, t.department.name(language)) for t in saved.tickets.all()]
    context = {
        "saved": saved,
        "tickets": tickets,
        "new": "new" in request.GET,
        "link": request.build_absolute_uri(status_url(saved)),
    }
    return render(request, "support/request_status.html", context)
