import random
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from doctors.models import Doctor


class Patient(models.Model):
    name = models.CharField(max_length=150)
    email = models.EmailField()  # required — the only channel used for OTP verification in v1
    phone = models.CharField(max_length=20, blank=True)  # optional, informational only (e.g. for staff to call)

    def __str__(self):
        return self.name


class Appointment(models.Model):
    class Status(models.TextChoices):
        BOOKED = "booked", "Booked"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="appointments")
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="appointments")
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.BOOKED)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    # Staff involvement is optional — null means the patient acted directly, unauthenticated (verified via OTP instead).
    booked_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="appointments_booked",
    )
    cancelled_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="appointments_cancelled",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "date", "start_time"],
                condition=models.Q(status="booked"),
                name="unique_active_slot",
            )
        ]
        ordering = ["date", "start_time"]

    def clean(self):
        if self.start_time >= self.end_time:
            raise ValidationError("start_time must be before end_time.")

    def __str__(self):
        return f"{self.patient.name} with {self.doctor.name} on {self.date} {self.start_time}"


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATED = "created", "Created"
        CANCELLED = "cancelled", "Cancelled"
        RESCHEDULED = "rescheduled", "Rescheduled"
        UPDATED = "updated", "Updated"

    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, related_name="audit_logs")
    action = models.CharField(max_length=20, choices=Action.choices)
    # Null = the patient acted directly (self-service, verified via OTP). A real User = staff acted.
    performed_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
    )
    notes = models.CharField(max_length=255, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Audit Logs"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.action} on {self.appointment_id} at {self.timestamp}"


class OTP(models.Model):
    """One-time codes used to verify a patient acting on their own appointment
    without an authenticated account. Not required for staff (authenticated Users),
    since their session and audit log entry already provide accountability."""

    class Purpose(models.TextChoices):
        CANCEL = "cancel", "Cancel"
        RESCHEDULE = "reschedule", "Reschedule"

    appointment = models.ForeignKey(Appointment, on_delete=models.CASCADE, related_name="otps")
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        verbose_name = "OTP"
        verbose_name_plural = "OTPs"

    @staticmethod
    def generate_code():
        return f"{random.randint(0, 999999):06d}"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    def __str__(self):
        return f"OTP({self.purpose}) for {self.appointment_id}"