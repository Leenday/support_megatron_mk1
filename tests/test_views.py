"""Requester pages: the open form and the status link (web/support/views.py, #17)."""

import pytest
from django.core.cache import cache
from django.urls import reverse

from megatron.departments import load_departments
from megatron.llm import FakeExtractor
from support.models import Request, Ticket
from support.services import import_departments

pytestmark = pytest.mark.django_db

RU = {"accept-language": "ru"}
EN = {"accept-language": "en"}


@pytest.fixture(autouse=True)
def service(departments_path, monkeypatch):
    """Departments in the database, the keyword backend instead of a model, no rate history."""
    import_departments(load_departments(departments_path))
    monkeypatch.setattr("support.services.default_extractor", FakeExtractor)
    cache.clear()


def send(client, text="Не работает VPN, сеть пропала", contact="ivanov@example.com", **kw):
    return client.post(reverse("request_form"), {"text": text, "contact": contact}, **kw)


def test_form_needs_no_login(client):
    response = client.get(reverse("request_form"), headers=RU)
    assert response.status_code == 200
    assert "Опишите проблему своими словами" in response.content.decode()


def test_request_becomes_a_ticket_with_a_status_link(client):
    response = send(client, headers=RU, follow=True)

    saved = Request.objects.get()
    ticket = saved.tickets.get()
    assert saved.contact == "ivanov@example.com"
    assert saved.requester is None
    assert ticket.department_id == "network"
    url, status = response.redirect_chain[0]
    assert status == 302
    assert url == f"/status/{saved.pk}-{saved.access_code}/?new=1"
    page = response.content.decode()
    assert f"Заявка №{ticket.pk} принята и направлена в отдел «Сеть и связь»" in page
    assert f"/status/{saved.pk}-{saved.access_code}/" in page


def test_department_is_named_in_the_interface_language(client):
    response = send(client, headers=EN, follow=True)
    assert "sent to “Network and communications”" in response.content.decode()


def test_status_page_shows_the_status(client):
    send(client)
    saved = Request.objects.get()
    saved.tickets.update(status=Ticket.Status.IN_PROGRESS)
    page = client.get(f"/status/{saved.pk}-{saved.access_code}/", headers=RU).content.decode()
    assert "В работе" in page
    assert "принята" not in page  # the "accepted" notice is only shown right after sending


def test_wrong_code_shows_nothing(client):
    send(client)
    saved = Request.objects.get()
    assert client.get(f"/status/{saved.pk}-wrong{saved.access_code}/").status_code == 404
    assert client.get(f"/status/{saved.pk + 1}-{saved.access_code}/").status_code == 404


def test_every_request_gets_its_own_code(client):
    send(client)
    send(client)
    codes = list(Request.objects.values_list("access_code", flat=True))
    assert len(set(codes)) == 2


def test_contact_is_required(client):
    response = send(client, contact="", headers=RU)
    assert response.status_code == 200
    assert not Request.objects.exists()
    assert "Обязательное поле" in response.content.decode()


def test_failed_extraction_is_accepted_for_manual_routing(client, monkeypatch):
    class Broken(FakeExtractor):
        def complete(self, messages, schema):
            return "not json"

    monkeypatch.setattr("support.services.default_extractor", Broken)
    page = send(client, headers=RU, follow=True).content.decode()

    saved = Request.objects.get()
    assert saved.error
    assert f"Обращение №{saved.pk} принято. Специалист распределит его вручную." in page


def test_logged_in_user_is_kept_as_the_requester(client, django_user_model):
    user = django_user_model.objects.create_user("specialist", password="x")
    client.force_login(user)
    send(client)
    assert Request.objects.get().requester == user


def test_rate_limit(client, settings):
    settings.REQUEST_FORM_RATE = (2, 60)
    assert send(client).status_code == 302
    assert send(client).status_code == 302
    response = send(client, headers=RU)
    assert response.status_code == 429
    assert "Слишком много обращений" in response.content.decode()
    assert Request.objects.count() == 2
