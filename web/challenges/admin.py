from django.contrib import admin

from challenges.models import (
    OrangeAssignment,
    OrangeAssignmentResult,
    OrangeCheck,
    OrangeCheckCriterion,
    OrangeCheckIn,
    OrangeFollowUp,
)


class OrangeCheckCriterionInline(admin.TabularInline):  # type: ignore[type-arg]
    model = OrangeCheckCriterion
    extra = 1


class OrangeAssignmentResultInline(admin.TabularInline):  # type: ignore[type-arg]
    model = OrangeAssignmentResult
    extra = 0


@admin.register(OrangeCheckIn)
class OrangeCheckInAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("user", "checked_in_at", "checked_out_at", "is_active")
    list_filter = ("is_active",)
    search_fields = ("user__username",)


@admin.register(OrangeCheck)
class OrangeCheckAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("title", "status", "created_by", "created_at")
    list_filter = ("status",)
    search_fields = ("title",)
    inlines = [OrangeCheckCriterionInline]


@admin.register(OrangeAssignment)
class OrangeAssignmentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("orange_check", "user", "team", "status", "score", "submitted_at")
    list_filter = ("status",)
    search_fields = ("user__username", "team__team_name")
    inlines = [OrangeAssignmentResultInline]


@admin.register(OrangeFollowUp)
class OrangeFollowUpAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("user", "assignment", "remind_at", "dismissed")
    list_filter = ("dismissed",)
