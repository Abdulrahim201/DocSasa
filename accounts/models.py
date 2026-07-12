from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Staff only — receptionists (and admins). Patients never get an account;
    they're represented by the separate Patient model in the appointments app."""

    class Role(models.TextChoices):
        RECEPTIONIST = "receptionist", "Receptionist"
        ADMIN = "admin", "Admin"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.RECEPTIONIST,
    )

    def __str__(self):
        return self.get_full_name() or self.username