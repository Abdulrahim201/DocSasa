from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Doctor(models.Model):
    name = models.CharField(max_length=150)
    specialty = models.CharField(max_length=150, blank=True)

    def clean(self):
        # Based on use case given set to 5 doctors from settings (default 5),
        # without hardcoding the limit into the model itself.
        max_doctors = getattr(settings, "MAX_DOCTORS", 5)
        existing_count = Doctor.objects.exclude(pk=self.pk).count()
        if existing_count >= max_doctors:
            raise ValidationError(
                f"Cannot add more than {max_doctors} doctors in this system."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class WorkingHours(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    doctor = models.ForeignKey(
        Doctor, on_delete=models.CASCADE, related_name="working_hours"
    )
    weekday = models.IntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "weekday"],
                name="unique_doctor_weekday",
            )
        ]
        ordering = ["weekday", "start_time"]

    def clean(self):
        if self.start_time >= self.end_time:
            raise ValidationError("start_time must be before end_time.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.doctor.name} — {self.get_weekday_display()} {self.start_time}-{self.end_time}"