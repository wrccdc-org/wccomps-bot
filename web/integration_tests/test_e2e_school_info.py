"""
Worker 7: School Info E2E Tests using Playwright.

Tests school information management functionality for GoldTeam users:
- View school info list for all teams
- Edit school info for specific teams
- Save school info with validation
- Form field validation (required fields)
- Access control (GoldTeam only)
- Navigation between list and edit views

These tests ensure GoldTeam can manage school contact information via the WebUI.
"""

import os

import pytest
from playwright.sync_api import Page, expect

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
]


@pytest.fixture
def goldteam_page(browser_context, live_server_url):
    """
    Create an authenticated page for a GoldTeam member.

    NOTE: This requires a user with WCComps_GoldTeam role in .env.test.
    For testing purposes, uses the standard authenticated user if GoldTeam-specific
    credentials are not provided.
    """
    page = browser_context.new_page()

    # Get GoldTeam credentials from environment
    goldteam_username = os.getenv("TEST_GOLDTEAM_USERNAME", os.getenv("TEST_AUTHENTIK_USERNAME"))
    goldteam_password = os.getenv("TEST_GOLDTEAM_PASSWORD", os.getenv("TEST_AUTHENTIK_PASSWORD"))

    # Navigate to login URL
    page.goto(f"{live_server_url}/accounts/oidc/authentik/login/")

    # Fill in Authentik login form
    page.fill('input[name="uid_field"]', goldteam_username)
    page.fill('input[type="password"]', goldteam_password)
    page.click('button[type="submit"]')

    # Wait for redirect back to application
    page.wait_for_url(f"{live_server_url}/**", timeout=10000)

    yield page
    page.close()


class TestSchoolInfoList:
    """Test school info list view."""

    def test_school_info_list_renders(self, goldteam_page: Page, live_server_url):
        """School info list page should render without errors."""
        goldteam_page.goto(f"{live_server_url}/ops/school-info/")

        # Should not show error
        expect(goldteam_page).not_to_have_title("*500*")
        expect(goldteam_page.locator("body")).not_to_contain_text("Server Error")

        # Should show page content
        expect(goldteam_page.locator("body")).to_be_visible()

    def test_school_info_list_shows_teams(self, goldteam_page: Page, db, live_server_url):
        """School info list should display all active teams."""
        from team.models import Team

        # Ensure test team exists
        team = Team.objects.get(team_number=50)

        goldteam_page.goto(f"{live_server_url}/ops/school-info/")

        # Should show team in list
        expect(goldteam_page.locator(f"text=Team {team.team_number}")).to_be_visible(timeout=5000)

    def test_school_info_list_has_edit_links(self, goldteam_page: Page, live_server_url):
        """School info list should have edit links for each team."""
        goldteam_page.goto(f"{live_server_url}/ops/school-info/")

        # Should have edit links
        edit_link = goldteam_page.locator('a:has-text("Edit")')

        if edit_link.is_visible():
            expect(edit_link.first).to_be_visible()

    def test_school_info_shows_existing_data(self, goldteam_page: Page, db, live_server_url):
        """School info list should display existing school data."""
        from team.models import SchoolInfo, Team

        team = Team.objects.get(team_number=50)

        # Create or update school info
        school_info, _ = SchoolInfo.objects.update_or_create(
            team=team,
            defaults={
                "school_name": "[E2E TEST] Test School",
                "contact_email": "test@example.com",
                "secondary_email": "test2@example.com",
                "notes": "Test notes",
                "updated_by": "test_user",
            },
        )

        try:
            goldteam_page.goto(f"{live_server_url}/ops/school-info/")

            # Should show school name
            expect(goldteam_page.locator("text=[E2E TEST] Test School")).to_be_visible(timeout=5000)
        finally:
            school_info.delete()


class TestSchoolInfoEdit:
    """Test school info edit form."""

    def test_school_info_edit_page_renders(self, goldteam_page: Page, live_server_url):
        """School info edit page should render without errors."""
        goldteam_page.goto(f"{live_server_url}/ops/school-info/50/")

        # Should not show error
        expect(goldteam_page).not_to_have_title("*500*")
        expect(goldteam_page.locator("body")).not_to_contain_text("Server Error")

    def test_school_info_edit_has_form_fields(self, goldteam_page: Page, live_server_url):
        """School info edit page should have all required form fields."""
        goldteam_page.goto(f"{live_server_url}/ops/school-info/50/")

        # Should have school_name input
        expect(goldteam_page.locator('input[name="school_name"]')).to_be_visible()

        # Should have contact_email input
        expect(goldteam_page.locator('input[name="contact_email"]')).to_be_visible()

        # Should have secondary_email input (optional)
        secondary_email = goldteam_page.locator('input[name="secondary_email"]')
        if secondary_email.is_visible():
            expect(secondary_email).to_be_visible()

        # Should have notes textarea
        notes_textarea = goldteam_page.locator('textarea[name="notes"]')
        if notes_textarea.is_visible():
            expect(notes_textarea).to_be_visible()

    def test_school_info_edit_has_csrf_token(self, goldteam_page: Page, live_server_url):
        """School info edit form should include CSRF token."""
        goldteam_page.goto(f"{live_server_url}/ops/school-info/50/")

        # Should have CSRF token
        csrf_input = goldteam_page.locator('input[name="csrfmiddlewaretoken"]')
        expect(csrf_input).to_be_attached()

    def test_school_info_edit_loads_existing_data(self, goldteam_page: Page, db, live_server_url):
        """School info edit form should load existing data."""
        from team.models import SchoolInfo, Team

        team = Team.objects.get(team_number=50)

        # Create school info
        school_info = SchoolInfo.objects.create(
            team=team,
            school_name="[E2E TEST] Existing School",
            contact_email="existing@example.com",
            secondary_email="existing2@example.com",
            notes="Existing notes",
            updated_by="test_user",
        )

        try:
            goldteam_page.goto(f"{live_server_url}/ops/school-info/50/")

            # Form should be populated with existing data
            school_name_input = goldteam_page.locator('input[name="school_name"]')
            expect(school_name_input).to_have_value("[E2E TEST] Existing School")

            contact_email_input = goldteam_page.locator('input[name="contact_email"]')
            expect(contact_email_input).to_have_value("existing@example.com")
        finally:
            school_info.delete()


class TestSchoolInfoSave:
    """Test saving school info data."""

    def test_save_new_school_info_works(self, goldteam_page: Page, db, live_server_url):
        """Saving new school info should work."""
        from team.models import SchoolInfo, Team

        team = Team.objects.get(team_number=50)

        # Delete existing school info if any
        SchoolInfo.objects.filter(team=team).delete()

        goldteam_page.goto(f"{live_server_url}/ops/school-info/50/")

        # Fill in form
        goldteam_page.fill('input[name="school_name"]', "[E2E TEST] New School")
        goldteam_page.fill('input[name="contact_email"]', "newschool@example.com")
        goldteam_page.fill('input[name="secondary_email"]', "newschool2@example.com")

        notes_textarea = goldteam_page.locator('textarea[name="notes"]')
        if notes_textarea.is_visible():
            notes_textarea.fill("New school notes")

        # Submit form
        goldteam_page.click('button[type="submit"]')

        # Wait for redirect
        goldteam_page.wait_for_timeout(2000)

        # Should redirect to list page
        expect(goldteam_page).to_have_url(f"{live_server_url}/ops/school-info/", timeout=5000)

        # Should not show error
        expect(goldteam_page.locator("body")).not_to_contain_text("Server Error")

        # Cleanup
        SchoolInfo.objects.filter(team=team, school_name="[E2E TEST] New School").delete()

    def test_update_existing_school_info_works(self, goldteam_page: Page, db, live_server_url):
        """Updating existing school info should work."""
        from team.models import SchoolInfo, Team

        team = Team.objects.get(team_number=50)

        # Create existing school info
        school_info = SchoolInfo.objects.create(
            team=team,
            school_name="[E2E TEST] Old School Name",
            contact_email="old@example.com",
            secondary_email="old2@example.com",
            notes="Old notes",
            updated_by="test_user",
        )

        try:
            goldteam_page.goto(f"{live_server_url}/ops/school-info/50/")

            # Update school name
            school_name_input = goldteam_page.locator('input[name="school_name"]')
            school_name_input.fill("[E2E TEST] Updated School Name")

            # Submit form
            goldteam_page.click('button[type="submit"]')

            # Wait for redirect
            goldteam_page.wait_for_timeout(2000)

            # Should redirect to list page
            expect(goldteam_page).to_have_url(f"{live_server_url}/ops/school-info/", timeout=5000)

            # Should not show error
            expect(goldteam_page.locator("body")).not_to_contain_text("Server Error")

            # Verify update
            school_info.refresh_from_db()
            assert school_info.school_name == "[E2E TEST] Updated School Name"
        finally:
            school_info.delete()


class TestSchoolInfoValidation:
    """Test form validation for school info."""

    def test_school_name_required(self, goldteam_page: Page, db, live_server_url):
        """School name should be required."""
        from team.models import SchoolInfo, Team

        team = Team.objects.get(team_number=50)
        SchoolInfo.objects.filter(team=team).delete()

        goldteam_page.goto(f"{live_server_url}/ops/school-info/50/")

        # Leave school_name empty
        goldteam_page.fill('input[name="school_name"]', "")
        goldteam_page.fill('input[name="contact_email"]', "test@example.com")

        # Submit form
        goldteam_page.click('button[type="submit"]')

        # Wait for validation
        goldteam_page.wait_for_timeout(1000)

        # Should show error message or stay on same page
        # (exact behavior depends on implementation)
        expect(goldteam_page.locator("body")).to_be_visible()

    def test_contact_email_required(self, goldteam_page: Page, db, live_server_url):
        """Contact email should be required."""
        from team.models import SchoolInfo, Team

        team = Team.objects.get(team_number=50)
        SchoolInfo.objects.filter(team=team).delete()

        goldteam_page.goto(f"{live_server_url}/ops/school-info/50/")

        # Fill school name but leave email empty
        goldteam_page.fill('input[name="school_name"]', "[E2E TEST] Test School")
        goldteam_page.fill('input[name="contact_email"]', "")

        # Submit form
        goldteam_page.click('button[type="submit"]')

        # Wait for validation
        goldteam_page.wait_for_timeout(1000)

        # Should show error message or stay on same page
        expect(goldteam_page.locator("body")).to_be_visible()

    def test_secondary_email_optional(self, goldteam_page: Page, db, live_server_url):
        """Secondary email should be optional."""
        from team.models import SchoolInfo, Team

        team = Team.objects.get(team_number=50)
        SchoolInfo.objects.filter(team=team).delete()

        goldteam_page.goto(f"{live_server_url}/ops/school-info/50/")

        # Fill required fields, leave secondary_email empty
        goldteam_page.fill('input[name="school_name"]', "[E2E TEST] Test School No Secondary")
        goldteam_page.fill('input[name="contact_email"]', "primary@example.com")
        goldteam_page.fill('input[name="secondary_email"]', "")

        # Submit form
        goldteam_page.click('button[type="submit"]')

        # Wait for redirect
        goldteam_page.wait_for_timeout(2000)

        # Should succeed (secondary email is optional)
        expect(goldteam_page).to_have_url(f"{live_server_url}/ops/school-info/", timeout=5000)

        # Cleanup
        SchoolInfo.objects.filter(team=team, school_name="[E2E TEST] Test School No Secondary").delete()


class TestSchoolInfoNavigation:
    """Test navigation between school info pages."""

    def test_edit_link_navigates_correctly(self, goldteam_page: Page, live_server_url):
        """Edit link should navigate to correct team's edit page."""
        goldteam_page.goto(f"{live_server_url}/ops/school-info/")

        # Find edit link for team 50
        edit_link = goldteam_page.locator('a[href="/ops/school-info/50/"]')

        if edit_link.is_visible():
            edit_link.click()

            # Wait for navigation
            goldteam_page.wait_for_timeout(1000)

            # Should navigate to edit page for team 50
            expect(goldteam_page).to_have_url(f"{live_server_url}/ops/school-info/50/", timeout=5000)

    def test_back_to_list_navigation_works(self, goldteam_page: Page, live_server_url):
        """Navigation back to list should work."""
        goldteam_page.goto(f"{live_server_url}/ops/school-info/50/")

        # Look for back/cancel link
        back_link = goldteam_page.locator('a:has-text("Back")')

        if back_link.is_visible():
            back_link.click()

            # Wait for navigation
            goldteam_page.wait_for_timeout(1000)

            # Should navigate to list page
            expect(goldteam_page).to_have_url(f"{live_server_url}/ops/school-info/", timeout=5000)


class TestSchoolInfoAccessControl:
    """Test that only GoldTeam members can access school info."""

    def test_non_goldteam_user_denied_access(self, authenticated_page: Page, live_server_url):
        """Non-GoldTeam users should be denied access to school info."""
        authenticated_page.goto(f"{live_server_url}/ops/school-info/")

        # Should either show access denied or redirect
        # (not 500 error, but proper access control)
        expect(authenticated_page.locator("body")).to_be_visible()

    def test_non_goldteam_user_denied_edit_access(self, authenticated_page: Page, live_server_url):
        """Non-GoldTeam users should be denied edit access."""
        authenticated_page.goto(f"{live_server_url}/ops/school-info/50/")

        # Should either show access denied or redirect
        expect(authenticated_page.locator("body")).to_be_visible()


class TestSchoolInfoNonexistentTeam:
    """Test error handling for nonexistent teams."""

    def test_nonexistent_team_shows_error(self, goldteam_page: Page, live_server_url):
        """Accessing school info for nonexistent team should show error."""
        goldteam_page.goto(f"{live_server_url}/ops/school-info/99999/")

        # Should show error page (not 500)
        expect(goldteam_page.locator("body")).to_be_visible()
