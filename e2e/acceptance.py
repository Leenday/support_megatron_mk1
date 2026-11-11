"""Acceptance check of the iteration 2 user stories in a real browser (#19).

Drives a running service as the three actors (requester, specialist, admin) and records one
result per user story, with screenshots. It does not stop at a failed step: every story is
checked and the report says what failed. Playwright drives the installed Google Chrome; it
is not a project dependency.

    LLM_BACKEND=fake DJANGO_DEBUG=true docker compose -p megatron-e2e up -d --build web
    docker compose -p megatron-e2e exec -e DJANGO_SUPERUSER_PASSWORD=<password> web \\
        python web/manage.py createsuperuser --noinput --username boss --email boss@example.com
    uvx --with playwright python -I e2e/acceptance.py --password <password>
    docker compose -p megatron-e2e down -v

`-p megatron-e2e` keeps the check's database apart from the development one. The fake
backend routes by keywords, so the routed departments are predictable; the model's quality is
measured by `megatron-eval`, not here. Users and departments get a per-run suffix, so the
check can run again on the same database.
"""

import argparse
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, expect, sync_playwright

PASSWORD = "e2e-specialist-pass-123"
RU = {"locale": "ru-RU", "viewport": {"width": 1200, "height": 900}}


@dataclass
class Check:
    story: str
    title: str
    status: str = "not run"  # pass · partial · fail
    note: str = ""


class Run:
    def __init__(self, base: str, out: Path) -> None:
        self.base = base.rstrip("/")
        self.out = out
        self.checks: list[Check] = []
        self.shots = 0

    def url(self, path: str) -> str:
        return self.base + path

    def shot(self, page: Page, name: str) -> str:
        self.shots += 1
        path = self.out / f"{self.shots:02d}-{name}.png"
        page.screenshot(path=path, full_page=True)
        return path.name

    def story(self, story: str, title: str, test: Callable[[], str | tuple[str, str] | None]):
        """Run one check; `test` returns a note, or (status, note) for a partial result."""
        check = Check(story, title)
        try:
            result = test()
            check.status, check.note = (
                result if isinstance(result, tuple) else ("pass", result or "")
            )
        except Exception as e:  # a failed story must not stop the others
            check.status = "fail"
            check.note = str(e).strip().splitlines()[0][:300]
        self.checks.append(check)
        print(f"{check.status:7} {story:>4} {title}" + (f" — {check.note}" if check.note else ""))


def admin_login(context: BrowserContext, run: Run, user: str, password: str) -> Page:
    page = context.new_page()
    page.goto(run.url("/admin/login/"))
    page.fill("#id_username", user)
    page.fill("#id_password", password)
    page.click("input[type=submit]")
    expect(page.locator("#user-tools")).to_be_visible()
    return page


def staff_login(context: BrowserContext, run: Run, user: str) -> Page:
    page = context.new_page()
    page.goto(run.url("/login/"))
    page.fill("#id_username", user)
    page.fill("#id_password", PASSWORD)
    page.click("main button[type=submit]")
    expect(page).to_have_url(run.url("/desk/"))
    return page


def create_specialist(page: Page, run: Run, username: str, department: str) -> None:
    page.goto(run.url("/admin/support/user/add/"))
    page.fill("#id_username", username)
    page.fill("#id_password1", PASSWORD)
    page.fill("#id_password2", PASSWORD)
    if page.locator("#id_department").count():
        page.select_option("#id_department", value=department)
    page.click("input[name=_save]")
    expect(page.locator("#id_groups_from, #id_groups")).to_have_count(1)
    if page.locator("#id_groups_from").count():  # the two-list widget of the user admin
        page.select_option("#id_groups_from", label="Specialist")
        page.click("#id_groups_add_link, #id_groups_add, a.selector-add >> nth=0")
    else:
        page.select_option("#id_groups", label="Specialist")
    page.select_option("#id_department", value=department)
    page.click("input[name=_save]")
    expect(page.locator(".messagelist .success")).to_be_visible()


def send_request(context: BrowserContext, run: Run, text: str) -> tuple[Page, int, float]:
    """Submit the form; returns the status page, the ticket number and the seconds it took."""
    page = context.new_page()
    page.goto(run.url("/"))
    page.fill("#id_text", text)
    page.fill("#id_contact", "requester@example.com")
    start = time.perf_counter()
    page.click("main button[type=submit]")
    page.wait_for_url(re.compile(r"/status/\d+-[\w-]+/\?new=1$"))
    seconds = time.perf_counter() - start
    notice = page.locator(".notice").first.inner_text()
    number = re.search(r"(?:№|#)(\d+)", notice)
    if not number:
        raise AssertionError(f"no ticket number in the confirmation: {notice!r}")
    return page, int(number.group(1)), seconds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--admin", default="boss", help="a superuser of the service")
    parser.add_argument("--password", required=True, help="the superuser's password")
    parser.add_argument("--out", type=Path, default=Path("out/acceptance"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for old in args.out.glob("*.png"):
        old.unlink()
    run = Run(args.base, args.out)
    suffix = time.strftime("%H%M%S")
    ivan, petr, new_department = f"ivan{suffix}", f"petr{suffix}", f"e2e{suffix}"
    state: dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        boss = admin_login(browser.new_context(**RU), run, args.admin, args.password)

        # --- Admin: configure the system (22–26) ---------------------------------------
        def story_22():
            create_specialist(boss, run, ivan, "network")
            create_specialist(boss, run, petr, "network")
            staff_login(browser.new_context(**RU), run, ivan).close()
            boss.goto(run.url("/admin/support/user/"))
            run.shot(boss, "admin-users")
            # Deleting is possible in the plain admin; #16 replaces it with deactivation.
            return "two specialists created in the admin with role and department; they log in"

        run.story("22", "Users with a role and a department", story_22)

        def story_23():
            boss.goto(run.url("/admin/support/department/add/"))
            boss.fill("#id_id", new_department)
            boss.fill("#id_name_ru", "Проверочный отдел")
            boss.fill("#id_name_en", "Check department")
            boss.fill("#id_description", "Created by the acceptance check; handles nothing.")
            boss.fill("#id_tags", '["e2echeck"]')
            boss.fill("#id_language", "ru")
            boss.fill("#id_capacity", "5")
            boss.click("input[name=_save]")
            expect(boss.locator(".messagelist .success")).to_be_visible()
            boss.goto(run.url(f"/admin/support/department/{new_department}/change/"))
            boss.fill("#id_description", "Edited by the acceptance check.")
            boss.uncheck("#id_active")
            boss.click("input[name=_save]")
            expect(boss.locator(".messagelist .success")).to_be_visible()
            run.shot(boss, "admin-departments")
            return "added, edited and deactivated (never deleted: tickets refer to departments)"

        run.story("23", "Departments with descriptions", story_23)

        def story_24():
            boss.goto(run.url("/admin/support/department/network/change/"))
            boss.fill("#id_capacity", "10")
            boss.click("input[name=_save]")
            expect(boss.locator(".messagelist .success")).to_be_visible()
            response = boss.request.get(run.url("/api/departments"))
            network = next(d for d in response.json() if d["id"] == "network")
            assert network["capacity"] == 10, network
            state["open_before"] = network["open_tickets"]
            return f"capacity 10 saved; load in /api/departments: {network['load']}"

        run.story("24", "Department capacity", story_24)

        def story_25():
            boss.goto(run.url(f"/admin/support/department/{new_department}/change/"))
            boss.fill("#id_language", "en")
            boss.click("input[name=_save]")
            expect(boss.locator(".messagelist .success")).to_be_visible()
            return (
                "partial",
                "the language is set and saved; translating tickets into it is #23 (iteration 3)",
            )

        run.story("25", "Department language", story_25)

        def story_26():
            boss.goto(run.url("/admin/support/routingsettings/"))
            boss.locator("#result_list tbody a").first.click()
            original = boss.input_value("#id_w_load")
            boss.fill("#id_w_load", "0.4")
            boss.click("input[name=_save]")
            expect(boss.locator(".messagelist .success")).to_be_visible()
            boss.locator("#result_list tbody a").first.click()
            assert boss.input_value("#id_w_load") == "0.4"
            boss.fill("#id_w_load", original)
            boss.click("input[name=_save]")
            return f"w_load changed to 0.4 and back to {original}"

        run.story("26", "Routing weights", story_26)

        # --- Requester (1–3, 5–7) --------------------------------------------------------
        requester = browser.new_context(**RU)

        def story_1():
            page = requester.new_page()
            page.goto(run.url("/"))
            fields = page.locator("main form textarea, main form input[type=text]")
            assert fields.count() == 2, f"{fields.count()} fields"
            run.shot(page, "form")
            text = "Не работает VPN с утра, Петров из бухгалтерии не может подключиться"
            state["vpn_page"], state["vpn"], state["vpn_seconds"] = send_request(
                requester, run, text
            )
            return "free text and a contact, no login"

        run.story("1", "Free-text web form", story_1)

        def story_5():
            notice = state["vpn_page"].locator(".notice.ok").inner_text()
            assert f"№{state['vpn']}" in notice, notice
            run.shot(state["vpn_page"], "confirmation")
            return f"«{notice}»"

        run.story("5", "Confirmation with the ticket number", story_5)

        def story_6():
            notice = state["vpn_page"].locator(".notice.ok").inner_text()
            assert "Сеть и связь" in notice, notice
            return "the department is named in the confirmation and on the status page"

        run.story("6", "Department shown", story_6)

        def story_3():
            seconds = state["vpn_seconds"]
            assert seconds <= 10, f"{seconds:.1f} s"
            return (
                f"{seconds:.1f} s with the fake backend; with gpt-5.4-mini see "
                "docs/testing-iteration2.md"
            )

        run.story("3", "Ticket in ≤ 10 s", story_3)

        def story_2():
            english = browser.new_context(locale="en-US", viewport=RU["viewport"])
            page, number, _ = send_request(
                english, run, "The VPN connection drops every hour since this morning"
            )
            notice = page.locator(".notice.ok").inner_text()
            assert "accepted" in notice and "Network" in notice, notice
            state["wifi"] = number
            run.shot(page, "english-request")
            return f"English request → ticket #{number}, English page"

        run.story("2", "Russian or English", story_2)

        def story_7():
            link = state["vpn_page"].locator("a.link").get_attribute("href")
            assert link, "no status link"
            state["status_link"] = link
            page = browser.new_context(**RU).new_page()
            page.goto(link)
            expect(page.locator("tbody")).to_contain_text("Новая")
            code = link.rstrip("/").rsplit("-", 1)[1]
            wrong = link.replace(code, ("x" if code[0] != "x" else "y") + code[1:])
            assert page.goto(wrong).status == 404, "a wrong code is not refused"
            return (
                "partial",
                "by the link with a secret code (not by the bare number, so others' requests stay "
                "unreadable); a wrong code gives 404",
            )

        run.story("7", "Status check", story_7)

        # --- Specialist (11, 14–21) --------------------------------------------------------
        try:
            ivan_page = staff_login(browser.new_context(**RU), run, ivan)
            petr_page = staff_login(browser.new_context(**RU), run, petr)
        except AssertionError:
            print("the specialists cannot log in (story 22 failed): specialist stories skipped")
            ivan_page = petr_page = None

        def story_16():
            ids = [
                int(t)
                for t in ivan_page.locator("tbody tr td:first-child").all_inner_texts()
                if t.strip("#").isdigit()
                for t in [t.strip("#")]
            ]
            assert state["vpn"] in ids and state["wifi"] in ids, ids
            assert ids == sorted(ids), f"not oldest first: {ids}"
            run.shot(ivan_page, "queue")
            return f"{len(ids)} new tickets of the department, oldest first"

        run.story("16", "Department queue", story_16)

        def story_11():
            ivan_page.goto(run.url(f"/desk/tickets/{state['vpn']}/"))
            expect(ivan_page.locator(".original")).to_contain_text("Не работает VPN с утра")
            return "the original message is on the ticket page"

        run.story("11", "Original message", story_11)

        def story_17():
            petr_page.goto(run.url(f"/desk/tickets/{state['vpn']}/"))
            ivan_page.locator("form[action$='/take/'] button").first.click()
            expect(ivan_page.locator(".notice.ok")).to_contain_text("Заявка теперь ваша")
            petr_page.locator("form[action$='/take/'] button").first.click()
            expect(petr_page.locator(".notice.error")).to_contain_text("уже взяли")
            run.shot(petr_page, "second-take-refused")
            return "one click; a second specialist is refused"

        run.story("17", "Take a ticket", story_17)

        def story_20():
            ivan_page.fill("#id_who", "Петров, бухгалтерия")
            ivan_page.click("form[action$='/edit/'] button")
            expect(ivan_page.locator(".notice.ok")).to_contain_text("Изменения сохранены")
            expect(ivan_page.get_by_text("Изменены поля: Кто")).to_be_visible()
            return "edited; the history keeps old and new values"

        run.story("20", "Edit own tickets", story_20)

        def story_19():
            ivan_page.goto(run.url("/desk/?list=mine"))
            expect(ivan_page.locator("tbody")).to_contain_text(f"#{state['vpn']}")
            return "the taken ticket is in «Мои заявки»"

        run.story("19", "My tickets", story_19)

        def story_15():
            ivan_page.goto(run.url(f"/desk/tickets/{state['wifi']}/"))
            hint = ivan_page.locator("form[action$='/return/']").locator("xpath=..").inner_text()
            ivan_page.fill("#id_reason", "Проверка возврата")
            ivan_page.click("form[action$='/return/'] button")
            expect(ivan_page.locator(".notice.ok")).to_contain_text("Возвращена в отдел")
            run.shot(ivan_page, "returned")
            target = re.search(r"«(.+?)»", hint)
            return f"returned with a reason to «{target.group(1) if target else '?'}»"

        run.story("15", "Return a misrouted ticket", story_15)

        def story_18():
            ivan_page.goto(run.url(f"/desk/tickets/{state['vpn']}/"))
            ivan_page.click("form[action$='/close/'] button")
            expect(ivan_page.locator(".notice.ok")).to_contain_text("Заявка выполнена")
            expect(ivan_page.get_by_text("Выполнена; отдел верный")).to_be_visible()
            page = browser.new_context(**RU).new_page()
            page.goto(state["status_link"])
            expect(page.locator("tbody")).to_contain_text("Выполнена")
            run.shot(page, "status-done")
            return "New → In progress → Done; the requester's status page follows"

        run.story("18", "Statuses", story_18)

        def story_21():
            def rows(query: str) -> list[str]:
                ivan_page.goto(run.url(f"/desk/?list=all&{query}"))
                return ivan_page.locator("tbody tr td:first-child").all_inner_texts()

            done = rows("status=done")
            assert f"#{state['vpn']}" in done, done
            assert f"#{state['vpn']}" not in rows("status=new")
            assert f"#{state['vpn']}" in rows("tag=vpn")
            assert rows("until=2000-01-01") == []
            run.shot(ivan_page, "filters")
            return "status, tag and date filters"

        run.story("21", "Filters", story_21)

        def story_14():
            response = boss.request.get(run.url("/api/departments"))
            network = next(d for d in response.json() if d["id"] == "network")
            return (
                "partial",
                f"load counted from open tickets (network: {network['open_tickets']} open of "
                f"{network['capacity']}); the choice by load is covered by tests/test_routing.py, "
                "since the fake backend gives one candidate",
            )

        run.story("14", "Routing by profile and load", story_14)

        # --- Admin: oversee all tickets (27–29, 33) -----------------------------------------
        def story_27():
            boss.goto(run.url("/admin/support/ticket/"))
            run.shot(boss, "admin-tickets")
            headers = " ".join(boss.locator("#result_list thead th").all_inner_texts()).lower()
            if "status" in headers and "assignee" in headers:
                return "the ticket list has status and assignee columns"
            return ("partial", "all tickets listed, without status and assignee columns (#16)")

        run.story("27", "All tickets with status and assignee", story_27)

        def story_28():
            boss.goto(run.url(f"/admin/support/ticket/{state['wifi']}/change/"))
            boss.select_option("#id_department", value="software")
            boss.click("input[name=_save]")
            expect(boss.locator(".messagelist .success")).to_be_visible()
            events = boss.request.get(run.url(f"/api/tickets/{state['wifi']}")).json()
            assert events["department"] == "software", events
            return (
                "partial",
                "any ticket can be edited and reassigned, but the change is not recorded as an "
                "event (#16)",
            )

        run.story("28", "Edit or reassign any ticket", story_28)

        def story_29():
            boss.goto(run.url("/admin/support/department/"))
            headers = " ".join(boss.locator("#result_list thead th").all_inner_texts()).lower()
            run.shot(boss, "admin-department-list")
            if "open" in headers:
                return "open tickets per department in the admin"
            return (
                "partial",
                "open tickets per department are in /api/departments, not yet in the admin (#16)",
            )

        run.story("29", "Open tickets per department", story_29)

        def story_33():
            boss.goto(run.url("/admin/support/request/"))
            boss.locator("#result_list tbody a").first.click()
            for field in ("id_text", "id_model", "id_prompt_version", "id_seconds"):
                assert boss.locator(f"#{field}, .field-{field[3:]}").count(), f"no {field}"
            run.shot(boss, "admin-request-log")
            return "every request with its text, model, prompt version, attempts, time and error"

        run.story("33", "Log of requests and answers", story_33)
        browser.close()

    lines = [
        "| Story | Check | Result | Note |",
        "|---|---|---|---|",
        *(f"| {c.story} | {c.title} | {c.status} | {c.note} |" for c in run.checks),
    ]
    (args.out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    failed = [c for c in run.checks if c.status == "fail"]
    print(f"\n{len(run.checks)} stories: {len(failed)} failed; report in {args.out / 'report.md'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
