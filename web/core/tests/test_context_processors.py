"""Tests for context processors."""

import re
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory

from core.context_processors import NAV_MAPPING, permissions
from core.models import UserGroups

pytestmark = pytest.mark.django_db


@pytest.fixture
def request_factory():
    """Create a RequestFactory for generating mock requests."""
    return RequestFactory()


class TestPermissionsContextProcessor:
    """Test the permissions context processor."""

    def test_unauthenticated_user_returns_false_for_all_flags(self, request_factory):
        """Unauthenticated users should get False for all permission flags."""
        from django.contrib.auth.models import AnonymousUser

        request = request_factory.get("/")
        request.user = AnonymousUser()

        context = permissions(request)

        assert context["is_admin"] is False
        assert context["is_ticketing_admin"] is False
        assert context["is_ticketing_support"] is False
        assert context["is_gold_team"] is False
        assert context["is_blue_team"] is False
        assert context["is_red_team"] is False
        assert context["is_white_team"] is False
        assert context["is_orange_team"] is False
        assert context["authentik_username"] == ""

    def test_white_team_user_has_is_white_team_true(self, request_factory):
        """User in WCComps_WhiteTeam group should have is_white_team = True."""
        user = User.objects.create_user(username="whiteteam", password="test")
        UserGroups.objects.create(user=user, authentik_id="white-team-uid", groups=["WCComps_WhiteTeam"])

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_white_team"] is True
        assert context["is_orange_team"] is False
        assert context["is_gold_team"] is False
        assert context["is_blue_team"] is False
        assert context["is_red_team"] is False

    def test_orange_team_user_has_is_orange_team_true(self, request_factory):
        """User in WCComps_OrangeTeam group should have is_orange_team = True."""
        user = User.objects.create_user(username="orangeteam", password="test")
        UserGroups.objects.create(user=user, authentik_id="orange-team-uid", groups=["WCComps_OrangeTeam"])

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_orange_team"] is True
        assert context["is_white_team"] is False
        assert context["is_gold_team"] is False
        assert context["is_blue_team"] is False
        assert context["is_red_team"] is False

    def test_user_with_multiple_teams(self, request_factory):
        """User in both WhiteTeam and OrangeTeam should have both flags True."""
        user = User.objects.create_user(username="multipleams", password="test")
        UserGroups.objects.create(
            user=user, authentik_id="multiple-teams-uid", groups=["WCComps_WhiteTeam", "WCComps_OrangeTeam"]
        )

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_white_team"] is True
        assert context["is_orange_team"] is True

    def test_non_white_team_user_has_is_white_team_false(self, request_factory):
        """User not in WCComps_WhiteTeam group should have is_white_team = False."""
        user = User.objects.create_user(username="goldteam", password="test")
        UserGroups.objects.create(user=user, authentik_id="gold-team-uid", groups=["WCComps_GoldTeam"])

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_white_team"] is False
        assert context["is_orange_team"] is False
        assert context["is_gold_team"] is True

    def test_non_orange_team_user_has_is_orange_team_false(self, request_factory):
        """User not in WCComps_OrangeTeam group should have is_orange_team = False."""
        user = User.objects.create_user(username="admin", password="test")
        UserGroups.objects.create(user=user, authentik_id="admin-uid", groups=["WCComps_Discord_Admin"])

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_orange_team"] is False
        assert context["is_white_team"] is True
        assert context["is_admin"] is True

    def test_user_without_usergroups_returns_false(self, request_factory):
        """User without UserGroups should have all team flags False."""
        user = User.objects.create_user(username="nosocial", password="test")

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_white_team"] is False
        assert context["is_orange_team"] is False
        assert context["is_gold_team"] is False
        assert context["is_blue_team"] is False
        assert context["is_red_team"] is False


class TestNavMappingCoverage:
    """Verify all page views with subnav have NAV_MAPPING entries."""

    def _build_template_inheritance(self, templates_dir: Path) -> dict[str, str | None]:
        """Build mapping of template -> parent template."""
        inheritance: dict[str, str | None] = {}

        for template_path in templates_dir.rglob("*.html"):
            rel_path = str(template_path.relative_to(templates_dir))
            try:
                content = template_path.read_text()
                match = re.search(r'{%\s*extends\s*["\']([^"\']+)["\']\s*%}', content)
                inheritance[rel_path] = match.group(1) if match else None
            except Exception:
                inheritance[rel_path] = None

        return inheritance

    def _find_subnav_bases(self, templates_dir: Path) -> set[str]:
        """Find templates that define <c-nav> (subnav)."""
        subnav_bases = set()
        for template_path in templates_dir.rglob("*.html"):
            rel_path = str(template_path.relative_to(templates_dir))
            # Skip cotton components
            if rel_path.startswith("cotton/"):
                continue
            try:
                content = template_path.read_text()
                if "<c-nav>" in content:
                    subnav_bases.add(rel_path)
            except Exception:
                pass
        return subnav_bases

    def _extends_subnav_base(self, template: str, subnav_bases: set[str], inheritance: dict[str, str | None]) -> bool:
        """Check if template eventually extends a subnav-enabled base."""
        visited = set()
        current = template
        while current and current not in visited:
            if current in subnav_bases:
                return True
            visited.add(current)
            current = inheritance.get(current)
        return False

    def _map_views_to_templates(self, web_dir: Path) -> dict[str, str]:
        """Parse view files to map view function names to templates."""
        view_to_template: dict[str, str] = {}

        for view_file in web_dir.rglob("views*.py"):
            content = view_file.read_text()

            # Find render() calls with their function context
            current_func = None
            for line in content.split("\n"):
                func_match = re.match(r"def (\w+)\s*\(", line)
                if func_match:
                    current_func = func_match.group(1)

                if current_func:
                    render_match = re.search(r'render\s*\(\s*request\s*,\s*["\']([^"\']+)["\']', line)
                    if render_match:
                        view_to_template[current_func] = render_match.group(1)

        return view_to_template

    def _get_url_to_view_mapping(self) -> dict[str, str]:
        """Get URL name -> view function name mapping from Django."""
        from django.urls import URLPattern, URLResolver, get_resolver

        url_to_view: dict[str, str] = {}

        def extract(patterns, namespace=""):
            for pattern in patterns:
                if isinstance(pattern, URLResolver):
                    ns = f"{namespace}:{pattern.namespace}" if namespace else (pattern.namespace or "")
                    extract(pattern.url_patterns, ns)
                elif isinstance(pattern, URLPattern) and pattern.name:
                    view_name = getattr(pattern.callback, "__name__", "")
                    full_name = f"{namespace}:{pattern.name}" if namespace else pattern.name
                    if view_name:
                        url_to_view[full_name] = view_name

        extract(get_resolver().url_patterns)
        return url_to_view

    def test_subnav_pages_have_nav_mapping(self):
        """Pages with subnav should have NAV_MAPPING entries for highlighting."""
        web_dir = Path(__file__).parent.parent.parent
        templates_dir = web_dir / "templates"

        # Build inheritance graph and find subnav bases
        inheritance = self._build_template_inheritance(templates_dir)
        subnav_bases = self._find_subnav_bases(templates_dir)

        # Find all templates that extend subnav bases
        templates_with_subnav = {t for t in inheritance if self._extends_subnav_base(t, subnav_bases, inheritance)}

        # Map views to templates
        view_to_template = self._map_views_to_templates(web_dir)

        # Invert: template -> views
        template_to_views: dict[str, list[str]] = {}
        for view, template in view_to_template.items():
            template_to_views.setdefault(template, []).append(view)

        # Map URL names to views
        url_to_view = self._get_url_to_view_mapping()

        # Invert: view -> URL names
        view_to_urls: dict[str, list[str]] = {}
        for url_name, view_name in url_to_view.items():
            view_to_urls.setdefault(view_name, []).append(url_name)

        # Check each template with subnav
        missing = []
        for template in templates_with_subnav:
            # Skip cotton partials
            if template.startswith("cotton/"):
                continue

            views = template_to_views.get(template, [])
            for view in views:
                url_names = view_to_urls.get(view, [])
                for url_name in url_names:
                    # Use the URL name without namespace for lookup
                    lookup_name = url_name.split(":")[-1] if ":" in url_name else url_name
                    if lookup_name not in NAV_MAPPING:
                        missing.append(f"{url_name} -> {template}")

        if missing:
            pytest.fail(
                "URLs with subnav missing from NAV_MAPPING:\n" + "\n".join(f"  - {m}" for m in sorted(set(missing)))
            )
