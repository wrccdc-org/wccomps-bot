"""Admin configuration for person app."""

from django.contrib import admin
from django.http import HttpRequest
from .models import Person


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    """Admin interface for Person profiles."""

    list_display = [
        "authentik_username",
        "authentik_email",
        "discord_username",
        "team_display",
        "staff_role_display",
        "last_login_at",
    ]
    list_filter = ["created_at", "last_login_at"]
    search_fields = [
        "authentik_username",
        "authentik_email",
        "discord_username",
        "authentik_user_id",
    ]
    readonly_fields = [
        "user",
        "created_at",
        "updated_at",
        "last_login_at",
        "authentik_groups_display",
    ]
    ordering = ["authentik_username"]

    fieldsets = (
        (
            "User Account",
            {
                "fields": (
                    "user",
                    "authentik_username",
                    "authentik_email",
                    "authentik_user_id",
                )
            },
        ),
        (
            "Authentik Groups",
            {"fields": ("authentik_groups_display",)},
        ),
        (
            "Discord Integration",
            {"fields": ("discord_id", "discord_username")},
        ),
        (
            "Audit",
            {"fields": ("created_at", "updated_at", "last_login_at")},
        ),
    )

    def team_display(self, obj: Person) -> str:
        """Display team number or role."""
        team_num = obj.get_team_number()
        if team_num:
            return f"Team {team_num}"
        return "-"

    team_display.short_description = "Team"

    def staff_role_display(self, obj: Person) -> str:
        """Display staff role if applicable."""
        roles = []
        if obj.is_gold_team():
            roles.append("Gold")
        if obj.is_white_team():
            roles.append("White")
        if obj.is_red_team():
            roles.append("Red")
        if obj.is_orange_team():
            roles.append("Orange")
        if obj.is_black_team():
            roles.append("Black")
        return ", ".join(roles) if roles else "-"

    staff_role_display.short_description = "Staff Role"

    def authentik_groups_display(self, obj: Person) -> str:
        """Display Authentik groups as comma-separated list."""
        if obj.authentik_groups:
            return ", ".join(obj.authentik_groups)
        return "No groups"

    authentik_groups_display.short_description = "Authentik Groups"

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Disable manual creation (auto-created via signal)."""
        return False

    def has_delete_permission(self, request: HttpRequest, obj=None) -> bool:
        """Disable deletion (managed via User model)."""
        return False

    actions = ["refresh_from_authentik"]

    @admin.action(description="Refresh Authentik data for selected users")
    def refresh_from_authentik(self, request: HttpRequest, queryset):
        """Refresh cached Authentik data from SocialAccount."""
        count = 0
        for person in queryset:
            person.refresh_from_authentik()
            count += 1
        self.message_user(request, f"Refreshed Authentik data for {count} user(s)")
