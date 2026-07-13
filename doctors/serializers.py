from rest_framework import serializers

from .models import Doctor, WorkingHours


class WorkingHoursSerializer(serializers.ModelSerializer):
    weekday_label = serializers.CharField(source="get_weekday_display", read_only=True)

    class Meta:
        model = WorkingHours
        fields = ["id", "weekday", "weekday_label", "start_time", "end_time"]

    def validate(self, attrs):
        start = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start is not None and end is not None and start >= end:
            raise serializers.ValidationError("start_time must be before end_time.")
        return attrs


class DoctorSerializer(serializers.ModelSerializer):
    working_hours = WorkingHoursSerializer(many=True, read_only=True)

    class Meta:
        model = Doctor
        fields = ["id", "name", "specialty", "working_hours"]

    def validate(self, attrs):
        # Mirrors Doctor.clean()'s MAX_DOCTORS check, surfaced as a clean
        # 400 response instead of the ValidationError raised inside save().
        from django.conf import settings
        max_doctors = getattr(settings, "MAX_DOCTORS", 5)
        if self.instance is None and Doctor.objects.count() >= max_doctors:
            raise serializers.ValidationError(
                f"Cannot add more than {max_doctors} doctors in this system."
            )
        return attrs