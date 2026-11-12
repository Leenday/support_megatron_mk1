"""Plain registrations so the data can be seen during development; #16 builds the real admin."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from support.models import (
    ApiToken,
    Department,
    Request,
    RoutingSettings,
    System,
    Ticket,
    TicketEvent,
    User,
)


class StaffAdmin(UserAdmin):
    """Django's user admin plus the department, which a specialist needs for the queue (#18)."""

    fieldsets = (*(UserAdmin.fieldsets or ()), ("Department", {"fields": ("department",)}))
    add_fieldsets = (*UserAdmin.add_fieldsets, ("Department", {"fields": ("department",)}))
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "department")


admin.site.register(User, StaffAdmin)
admin.site.register([Department, System, RoutingSettings, Request, Ticket, TicketEvent])


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    """Tokens are issued by `manage.py create_api_token` (shown once); here they are revoked."""

    list_display = ["hint", "name", "user", "created_at", "last_used_at"]
    readonly_fields = ["user", "name", "hint", "created_at", "last_used_at"]

    def has_add_permission(self, request):
        return False
