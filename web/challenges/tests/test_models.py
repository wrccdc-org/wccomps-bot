import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError

from challenges.models import OrangeCheckIn

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
