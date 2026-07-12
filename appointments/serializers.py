from rest_framework import serializers
from doctors.models import Doctor
from .models import Appointment, Patient

# ---------------------------------------------------------------------------
# Output serializers — how an Appointment/Patient look coming back from the API
# ---------------------------------------------------------------------------

class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = ["id", "name", "email", "phone"]
        read_only_fields = fields  # patients are never edited directly through this serializer


class AppointmentSerializer(serializers.ModelSerializer):
    patient = PatientSerializer(read_only=True)
    doctor_name = serializers.CharField(source="doctor.name", read_only=True)
    booked_by = serializers.CharField(source="booked_by_user.username", read_only=True, default=None)

    class Meta:
        model = Appointment
        fields = [
            "id", "doctor", "doctor_name", "patient", "date", "start_time", "end_time",
            "status", "cancellation_reason", "booked_by", "created_at", "updated_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Availability — a single free slot, and the query params for the endpoint
# ---------------------------------------------------------------------------

class SlotSerializer(serializers.Serializer):
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()


class AvailabilityQuerySerializer(serializers.Serializer):
    date = serializers.DateField()


# ---------------------------------------------------------------------------
# Booking a new appointment
# ---------------------------------------------------------------------------

class BookAppointmentSerializer(serializers.Serializer):
    doctor = serializers.PrimaryKeyRelatedField(queryset=Doctor.objects.all())
    date = serializers.DateField()
    start_time = serializers.TimeField()
    patient_name = serializers.CharField(max_length=150)
    patient_email = serializers.EmailField()
    patient_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)

    # Only present when a receptionist is booking on a patient's behalf while
    # NOT authenticated through this API session (rare in practice — normally
    # the view infers this from request.user instead). Kept off by default;
    # not exposed as a writable field, listed here only for documentation.



# ---------------------------------------------------------------------------
# OTP-gated actions — shared base, plus cancel/reschedule specifics
# ---------------------------------------------------------------------------


class OTPVerifiedActionSerializer(serializers.Serializer):
    """Base for any patient-facing action that needs OTP verification when
    there's no authenticated staff user making the request. Subclasses add
    their own action-specific fields (e.g. `reason`, `new_date`)."""
    otp_code = serializers.CharField(max_length=6, required=False, allow_blank=True)

    def validate(self, attrs):
        request = self.context.get("request")
        is_staff_request = bool(request and request.user.is_authenticated)

        if not is_staff_request and not attrs.get("otp_code"):
            raise serializers.ValidationError({
                "otp_code": "This field is required when not logged in as staff."
            })
        return attrs


class CancelAppointmentSerializer(OTPVerifiedActionSerializer):
    reason = serializers.CharField(max_length=255)


class RescheduleAppointmentSerializer(OTPVerifiedActionSerializer):
    new_date = serializers.DateField()
    new_start_time = serializers.TimeField()


# ---------------------------------------------------------------------------
# Requesting an OTP (the step before a patient can cancel/reschedule)
# ---------------------------------------------------------------------------

class RequestOTPSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=["cancel", "reschedule"])