import logging

from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from uuid import uuid4
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import UserManager
from .utils import send_activation_email

logger = logging.getLogger(__name__)


class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=255)
    email = models.EmailField(max_length=255, unique=True)
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        db_table = "user"


class UserActivateTokenManager(models.Manager):
    def activate_user_by_token(self, token):
        user_activate_token = self.filter(
            token=token,
            expired_at__gte=timezone.now(),
        ).first()
        if not user_activate_token:
            raise ValueError("トークンが存在しません")

        user = user_activate_token.user
        user.is_active = True
        user.save()
        user_activate_token.delete()
        return user

    def create_or_update_token(self, user):
        token = str(uuid4())
        expired_at = timezone.now() + timedelta(days=1)
        user_token, created = self.update_or_create(
            user=user,
            defaults={
                "token": token,
                "expired_at": expired_at,
            },
        )
        return user_token


class UserActivateToken(models.Model):
    token = models.UUIDField(db_index=True, unique=True, default=uuid4)
    expired_at = models.DateTimeField()

    objects: UserActivateTokenManager = UserActivateTokenManager()

    user = models.OneToOneField(
        "User",
        on_delete=models.CASCADE,
        related_name="user_activate_token",
    )

    class Meta:
        db_table = "user_activate_token"


@receiver(post_save, sender=User)
def publish_token(sender, instance, created, **kwargs):
    if created:
        user_activate_token = UserActivateToken.objects.create_or_update_token(instance)
        try:
            send_activation_email(instance, user_activate_token.token)
        except Exception:
            logger.error(
                "アクティベーションメール送信に失敗しました。user_id=%s のトークンはDBに残っています。",
                instance.pk,
            )
