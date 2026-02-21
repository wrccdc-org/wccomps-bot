import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError

from challenges.models import OrangeCheck, OrangeCheckCriterion, OrangeCheckIn

pytestmark = pytest.mark.django_db


class TestOrangeCheckIn:
    def test_check_in(self) -> None:
        user = User.objects.create_user(username="orange1")
        checkin = OrangeCheckIn.objects.create(user=user)
        assert checkin.is_active
        assert checkin.checked_out_at is None

    def test_only_one_active_checkin(self) -> None:
        user = User.objects.create_user(username="orange1")
        OrangeCheckIn.objects.create(user=user)
        with pytest.raises(IntegrityError):
            OrangeCheckIn.objects.create(user=user)


class TestOrangeCheck:
    def test_create_check(self) -> None:
        user = User.objects.create_user(username="lead1")
        check = OrangeCheck.objects.create(title="Password Reset", description="Ask team to reset password", created_by=user)
        assert check.status == "draft"
        assert check.max_score == 0

    def test_max_score_from_criteria(self) -> None:
        check = OrangeCheck.objects.create(title="Test", description="Test")
        OrangeCheckCriterion.objects.create(orange_check=check, label="Fast response", points=3)
        OrangeCheckCriterion.objects.create(orange_check=check, label="Professional", points=3)
        OrangeCheckCriterion.objects.create(orange_check=check, label="Resolved", points=4)
        assert check.max_score == 10
