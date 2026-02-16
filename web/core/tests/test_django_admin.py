"""Validate all Django admin site registrations.

Catches misconfigurations like referencing fields that don't exist on models,
invalid inline setups, broken list_display/list_filter/search_fields, etc.
"""

import pytest
from django.contrib import admin
from django.core.checks import run_checks


@pytest.mark.django_db
class TestDjangoAdminConfig:
    def test_admin_site_checks_pass(self):
        """Run Django's admin system checks to catch field misconfigurations."""
        errors = run_checks(tags=["admin"])
        assert errors == [], "Django admin checks failed:\n" + "\n".join(f"  {e.id}: {e.msg}" for e in errors)

    def test_all_admin_inlines_reference_valid_fields(self):
        """Verify every inline's `fields` attribute only references real model fields."""
        errors = []
        for model, model_admin in admin.site._registry.items():
            for inline_cls in getattr(model_admin, "inlines", []):
                inline = inline_cls(model, admin.site)
                if not inline.fields:
                    continue
                model_field_names = {f.name for f in inline.model._meta.get_fields()}
                errors.extend(
                    f"{inline.__class__.__name__}: field '{field_name}' does not exist on {inline.model.__name__}"
                    for field_name in inline.fields
                    if field_name not in model_field_names
                )
        assert errors == [], "Admin inlines reference nonexistent fields:\n" + "\n".join(f"  {e}" for e in errors)
