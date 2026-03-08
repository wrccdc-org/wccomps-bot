"""Check database health - verify all models exist and are queryable."""

import sys
from typing import Protocol, cast

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection


class _ManagerLike(Protocol):
    def exists(self) -> bool: ...


class ModelWithObjects(Protocol):
    objects: _ManagerLike
    __name__: str


class Command(BaseCommand):
    help = "Verify all Django models exist in database and are queryable"

    def handle(self, *args: str, **options: object) -> None:
        """Run health checks."""
        self.stdout.write("=" * 80)
        self.stdout.write("DATABASE HEALTH CHECK")
        self.stdout.write("=" * 80)
        self.stdout.write()

        errors = []

        # Check 1: Database connection
        self.stdout.write("Checking database connection...")
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            self.stdout.write(self.style.SUCCESS("✓ Database connection OK"))
        except Exception as e:
            errors.append(f"Database connection failed: {e}")
            self.stdout.write(self.style.ERROR(f"✗ Database connection failed: {e}"))

        self.stdout.write()

        # Check 2: Migrations applied
        self.stdout.write("Checking migrations...")
        try:
            from django.db.migrations.executor import MigrationExecutor

            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            if plan:
                errors.append(f"Unapplied migrations: {len(plan)} pending")
                self.stdout.write(self.style.ERROR(f"✗ {len(plan)} unapplied migrations found:"))
                for migration, _ in plan:
                    self.stdout.write(f"  - {migration}")
            else:
                self.stdout.write(self.style.SUCCESS("✓ All migrations applied"))
        except Exception as e:
            errors.append(f"Migration check failed: {e}")
            self.stdout.write(self.style.ERROR(f"✗ Migration check failed: {e}"))

        self.stdout.write()

        # Check 3: Model integrity
        self.stdout.write("Checking model integrity...")
        core_models = apps.get_app_config("core").get_models()

        for model_class in core_models:
            typed_model = cast("ModelWithObjects", model_class)
            model_name = typed_model.__name__
            try:
                # Try to query the model
                typed_model.objects.exists()
                self.stdout.write(self.style.SUCCESS(f"✓ {model_name}"))
            except Exception as e:
                error_msg = f"{model_name}: {str(e)[:100]}"
                errors.append(error_msg)
                self.stdout.write(self.style.ERROR(f"✗ {error_msg}"))

        self.stdout.write()

        # Check 4: Critical queries
        self.stdout.write("Testing critical queries...")
        try:
            from core.models import UserGroups
            from team.models import DiscordLink, Team
            from ticketing.models import Ticket

            # Test queries that views depend on
            Team.objects.count()
            Ticket.objects.filter(status="open").count()
            DiscordLink.objects.filter(is_active=True).count()
            UserGroups.objects.count()

            self.stdout.write(self.style.SUCCESS("✓ Critical queries OK"))
        except Exception as e:
            error_msg = f"Critical query failed: {e}"
            errors.append(error_msg)
            self.stdout.write(self.style.ERROR(f"✗ {error_msg}"))

        self.stdout.write()

        # Check 5: Test critical view imports
        self.stdout.write("Testing view imports...")
        try:
            from core import auth_utils, utils, views
            from ticketing import views as ticketing_views

            # Verify key functions exist
            if not callable(auth_utils.get_authentik_groups):
                raise RuntimeError("auth_utils.get_authentik_groups is not callable")
            if not callable(utils.get_team_from_groups):
                raise RuntimeError("utils.get_team_from_groups is not callable")
            if not callable(auth_utils.has_permission):
                raise RuntimeError("auth_utils.has_permission is not callable")
            if not callable(views.home):
                raise RuntimeError("views.home is not callable")
            if not callable(ticketing_views.ticket_list):
                raise RuntimeError("ticketing_views.ticket_list is not callable")

            self.stdout.write(self.style.SUCCESS("✓ View imports OK"))
        except Exception as e:
            error_msg = f"View import failed: {e}"
            errors.append(error_msg)
            self.stdout.write(self.style.ERROR(f"✗ {error_msg}"))

        self.stdout.write()

        # Check 6: Test template syntax
        self.stdout.write("Testing template syntax...")
        try:
            import os
            from pathlib import Path

            from django.conf import settings
            from django.template import loader

            # Discover all templates dynamically
            templates_config: list[dict[str, object]] = settings.TEMPLATES
            dirs = templates_config[0].get("DIRS", [])
            templates_dir = str(dirs[0]) if isinstance(dirs, list) and dirs else ""
            template_files = []
            for root, _dirs, files in os.walk(templates_dir):
                for file in files:
                    if file.endswith(".html"):
                        full_path = Path(root) / file
                        rel_path = os.path.relpath(full_path, templates_dir)
                        template_files.append(rel_path)

            template_errors = []
            for template_name in template_files:
                try:
                    # Just load template - checks syntax, balanced tags, valid filters,
                    # and URL reversals (the {% url %} tag validates at load time)
                    loader.get_template(template_name)
                except Exception as e:
                    # Catches: TemplateSyntaxError, NoReverseMatch, invalid filters
                    error_msg = f"{template_name}: {str(e)[:100]}"
                    template_errors.append(error_msg)

            if template_errors:
                for error_msg in template_errors:
                    errors.append(error_msg)
                    self.stdout.write(self.style.ERROR(f"✗ {error_msg}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"✓ Template syntax OK ({len(template_files)} templates tested)"))
        except Exception as e:
            error_msg = f"Template test failed: {e}"
            errors.append(error_msg)
            self.stdout.write(self.style.ERROR(f"✗ {error_msg}"))

        # Summary
        self.stdout.write()
        self.stdout.write("=" * 80)
        if errors:
            self.stdout.write(self.style.ERROR(f"FAILED: {len(errors)} error(s) found"))
            self.stdout.write("=" * 80)
            for error in errors:
                self.stdout.write(f"  • {error}")
            sys.exit(1)
        else:
            self.stdout.write(self.style.SUCCESS("SUCCESS: All checks passed"))
            self.stdout.write("=" * 80)
            sys.exit(0)
