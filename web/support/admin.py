from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from support.forms import EmailLoginForm, StaffChangeForm, StaffCreationForm
from support.models import (
    ADMIN_ROLE,
    ROLES,
    Department,
    Request,
    RoutingSettings,
    Ticket,
    TicketEvent,
    User,
)


def is_admin(user):
    return user.is_active and user.is_authenticated and user.groups.filter(name=ADMIN_ROLE).exists()


class SupportAdminSite(admin.AdminSite):
    site_header = "Megatron · Панель управления"
    site_title = "Megatron"
    index_title = "Главная"
    site_url = None
    login_form = EmailLoginForm
    index_template = "support/admin_index.html"

    def has_permission(self, request):
        user = request.user
        return (
            user.is_active and user.is_authenticated and user.groups.filter(name__in=ROLES).exists()
        )

    def each_context(self, request):
        return {**super().each_context(request), "can_manage_users": is_admin(request.user)}


class StaffAdmin(UserAdmin):
    form = StaffChangeForm
    add_form = StaffCreationForm
    list_display = ("email", "role", "is_active")
    list_filter = ("is_active",)
    search_fields = ("email",)
    ordering = ("email",)
    filter_horizontal = ()
    fieldsets = ((None, {"fields": ("email", "password", "role", "is_active")}),)
    add_fieldsets = ((None, {"fields": ("email", "role", "password1", "password2")}),)

    @admin.display(description="Роль")
    def role(self, obj):
        return ", ".join(group.name for group in obj.groups.all() if group.name in ROLES)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("groups")

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
            obj.groups.remove(*obj.groups.filter(name__in=ROLES))
            obj.groups.add(form.cleaned_data["role"])


site = SupportAdminSite(name="admin")
site.register(User, StaffAdmin)
site.register([Department, RoutingSettings, Request, Ticket, TicketEvent])
