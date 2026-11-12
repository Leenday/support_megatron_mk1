import json

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import path
from django.utils.html import format_html_join
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from support import services, workflow
from support.forms import (
    DepartmentAdminForm,
    EmailLoginForm,
    RoutingAdminForm,
    StaffChangeForm,
    StaffCreationForm,
    TicketAdminForm,
)
from support.models import (
    ACCOUNT_ROLES,
    ROLE_LABELS,
    ApiToken,
    Department,
    Request,
    RoutingSettings,
    System,
    Ticket,
    TicketEvent,
    User,
)


def is_admin(user):
    return user.is_authenticated and user.can_access_admin()


class SupportAdminSite(admin.AdminSite):
    site_header = _("Megatron · Administration")
    site_title = "Megatron"
    index_title = _("Dashboard")
    site_url = None
    login_form = EmailLoginForm
    index_template = "support/admin_index.html"

    def has_permission(self, request):
        return is_admin(request.user)


class StaffAdmin(UserAdmin):
    form = StaffChangeForm
    add_form = StaffCreationForm
    list_display = ("email", "role", "department", "is_active")
    list_filter = ("is_active",)
    search_fields = ("email",)
    ordering = ("email",)
    filter_horizontal = ()
    fieldsets = ((None, {"fields": ("email", "password", "role", "department", "is_active")}),)
    add_fieldsets = ((None, {"fields": ("email", "role", "department", "password1", "password2")}),)

    @admin.display(description=_("Role"))
    def role(self, obj):
        return ", ".join(
            str(ROLE_LABELS[group.name])
            for group in obj.groups.all()
            if group.name in ACCOUNT_ROLES
        )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("department").prefetch_related("groups")

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.pk == request.user.pk:
            return ("role", "is_active")
        return ()

    def has_module_permission(self, request):
        return is_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return is_admin(request.user)

    def has_add_permission(self, request):
        return is_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_admin(request.user) and (
            obj is None or not obj.is_superuser or request.user.is_superuser
        )

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if "role" in form.cleaned_data:
            obj.groups.remove(*obj.groups.filter(name__in=ACCOUNT_ROLES))
            obj.groups.add(form.cleaned_data["role"])


site = SupportAdminSite(name="admin")
site.register(User, StaffAdmin)
site.register(System)


class SupportModelAdmin(admin.ModelAdmin):
    allow_add = False
    allow_change = False

    def has_module_permission(self, request):
        return is_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return is_admin(request.user)

    def has_add_permission(self, request):
        return self.allow_add and is_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return self.allow_change and is_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return False


class RoutingConfigAdmin(SupportModelAdmin):
    """Serialize changes to the languages and fallback shared by both forms."""

    allow_change = True

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        with transaction.atomic():
            if request.method == "POST" and is_admin(request.user):
                RoutingSettings.load()
                RoutingSettings.objects.select_for_update().get(pk=1)
            return super().changeform_view(request, object_id, form_url, extra_context)


@admin.register(Department, site=site)
class DepartmentAdmin(RoutingConfigAdmin):
    form = DepartmentAdminForm
    allow_add = True
    fields = (
        "id",
        "name_ru",
        "name_en",
        "description",
        "tags",
        "language",
        "capacity",
        "active",
        "make_fallback",
    )
    list_display = ("id", "display_name", "language", "active", "fallback")
    list_filter = ("active", "fallback", "language")
    search_fields = ("id", "name_ru", "name_en", "description")
    change_list_template = "support/department_changelist.html"

    def get_readonly_fields(self, request, obj=None):
        return ("id",) if obj is not None else ()

    def get_list_display(self, request):
        open_counts = services.open_ticket_counts()
        accuracy_counts = services.department_accuracy()

        @admin.display(description=_("Open tickets"))
        def open_tickets(obj):
            return open_counts.get(obj.pk, 0)

        @admin.display(description=_("Load"))
        def load(obj):
            if obj.capacity:
                return format(open_counts.get(obj.pk, 0) / obj.capacity, ".0%")
            return None

        @admin.display(description=_("Routing accuracy"))
        def accuracy(obj):
            correct, assessed = accuracy_counts.get(obj.pk, (0, 0))
            return f"{correct / assessed:.0%} ({correct}/{assessed})" if assessed else None

        return (*self.list_display, open_tickets, load, accuracy)

    @admin.display(description=_("Department name"))
    def display_name(self, obj):
        return obj.name(get_language() or "ru")

    def save_model(self, request, obj, form, change):
        obj.fallback = form.cleaned_data["make_fallback"]
        if obj.fallback:
            Department.objects.filter(fallback=True).exclude(pk=obj.pk).update(fallback=False)
        super().save_model(request, obj, form, change)

    def get_urls(self):
        return [
            path(
                "export/", self.admin_site.admin_view(self.export), name="support_department_export"
            ),
            *super().get_urls(),
        ]

    def export(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied
        response = HttpResponse(services.export_departments(), content_type="application/yaml")
        response.headers["Content-Disposition"] = 'attachment; filename="departments.yaml"'
        return response


@admin.register(RoutingSettings, site=site)
class RoutingSettingsAdmin(RoutingConfigAdmin):
    form = RoutingAdminForm

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_permission(request):
            raise PermissionDenied
        return redirect("admin:support_routingsettings_change", object_id=RoutingSettings.load().pk)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        if object_id != "1":
            raise Http404
        return super().change_view(request, object_id, form_url, extra_context)


@admin.register(Ticket, site=site)
class TicketAdmin(SupportModelAdmin):
    form = TicketAdminForm
    allow_change = True
    list_display = (
        "id",
        "summary",
        "status",
        "department",
        "assignee",
        "created_at",
        "taken_at",
        "closed_at",
    )
    list_filter = ("status", "department", "assignee", "created_at")
    list_select_related = ("department", "assignee")
    search_fields = ("=id", "summary", "what", "request__text", "assignee__email")
    readonly_fields = ("created_at", "taken_at", "closed_at", "history")

    @admin.display(description=_("Ticket history"))
    def history(self, obj):
        return format_html_join(
            " ",
            "<div><strong>{}</strong> · {} · {}<pre>{}</pre></div>",
            (
                (
                    event.get_kind_display(),
                    event.at,
                    event.actor or _("System"),
                    json.dumps(event.data, ensure_ascii=False, indent=2),
                )
                for event in obj.events.select_related("actor")
            ),
        )

    def save_model(self, request, obj, form, change):
        values = {
            field.attname: getattr(obj, field.attname)
            for field in obj._meta.concrete_fields
            if field.name in form.changed_data
        }
        workflow.admin_edit(obj.pk, request.user, values)
        obj.refresh_from_db()


class FailedRequestFilter(admin.SimpleListFilter):
    title = _("Extraction result")
    parameter_name = "result"

    def lookups(self, request, model_admin):
        return (("failed", _("Failed")), ("success", _("Succeeded")))

    def queryset(self, request, queryset):
        if self.value() == "failed":
            return queryset.exclude(error="")
        if self.value() == "success":
            return queryset.filter(error="")
        return queryset


@admin.register(Request, site=site)
class RequestAdmin(SupportModelAdmin):
    list_display = ("id", "created_at", "model", "prompt_version", "attempts", "seconds", "error")
    list_filter = (FailedRequestFilter, "model", "created_at")
    search_fields = ("=id", "text", "contact", "error")
    exclude = ("access_code",)


@admin.register(TicketEvent, site=site)
class TicketEventAdmin(SupportModelAdmin):
    list_display = ("ticket", "kind", "actor", "at")
    list_filter = ("kind", "at")


@admin.register(ApiToken, site=site)
class ApiTokenAdmin(admin.ModelAdmin):
    """Tokens are issued by `manage.py create_api_token` (shown once); here they are revoked."""

    list_display = ["hint", "name", "user", "created_at", "last_used_at"]
    readonly_fields = ["user", "name", "hint", "created_at", "last_used_at"]

    def has_add_permission(self, request):
        return False
