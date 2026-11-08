"""Plain registrations so the data can be seen during development; #16 builds the real admin."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from support.models import Department, Request, RoutingSettings, Ticket, TicketEvent, User

admin.site.register(User, UserAdmin)
admin.site.register([Department, RoutingSettings, Request, Ticket, TicketEvent])
