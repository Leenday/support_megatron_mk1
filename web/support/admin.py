"""Plain registrations so the data can be seen during development; #16 builds the real admin."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from support.models import ApiToken, Department, Request, RoutingSettings, Ticket, TicketEvent, User

admin.site.register(User, UserAdmin)
admin.site.register([Department, RoutingSettings, Request, Ticket, TicketEvent])


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    """Tokens are issued by `manage.py create_api_token` (shown once); here they are revoked."""

    list_display = ["hint", "name", "user", "created_at", "last_used_at"]
    readonly_fields = ["user", "name", "hint", "created_at", "last_used_at"]

    def has_add_permission(self, request):
        return False
