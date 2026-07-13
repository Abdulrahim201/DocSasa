from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Appointment
from .serializers import (
    AppointmentSerializer,
    BookAppointmentSerializer,
    CancelAppointmentSerializer,
    RequestOTPSerializer,
    RescheduleAppointmentSerializer,
)
from .services import (
    BookingError,
    SlotUnavailableError,
    book_appointment,
    cancel_appointment,
    reschedule_appointment,
    request_otp,
    verify_otp,
)
from datetime import date as date_cls

from rest_framework.permissions import AllowAny, IsAuthenticated

from .models import Patient

def _get_appointment_or_404(pk):
    try:
        return Appointment.objects.select_related("patient", "doctor").get(pk=pk)
    except Appointment.DoesNotExist:
        return None


class AppointmentListCreateView(APIView):
    """POST /appointments/ — public, no login required, no OTP required.
    Books a new appointment.

    GET /appointments/ — staff-only. Lists all appointments, optionally
    filtered by ?doctor=, ?date=, ?status=. Supports the staff dashboard's
    'manage appointments' screen."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [AllowAny()]

    def get(self, request):
        qs = Appointment.objects.select_related("doctor", "patient").order_by("date", "start_time")

        doctor_id = request.query_params.get("doctor")
        if doctor_id:
            qs = qs.filter(doctor_id=doctor_id)

        date_filter = request.query_params.get("date")
        if date_filter:
            qs = qs.filter(date=date_filter)

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        return Response(AppointmentSerializer(qs, many=True).data)

    def post(self, request):
        serializer = BookAppointmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        booked_by_user = request.user if request.user.is_authenticated else None

        try:
            appointment = book_appointment(
                doctor=data["doctor"],
                date=data["date"],
                start_time=data["start_time"],
                patient_name=data["patient_name"],
                patient_email=data["patient_email"],
                patient_phone=data.get("patient_phone", ""),
                booked_by_user=booked_by_user,
            )
        except SlotUnavailableError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(AppointmentSerializer(appointment).data, status=201)


class RequestOTPView(APIView):
    """POST /appointments/{id}/request-otp/ — public. Not needed by staff,
    but harmless if they call it (they just won't need the resulting code)."""
    permission_classes = [AllowAny]

    def post(self, request, pk):
        appointment = _get_appointment_or_404(pk)
        if appointment is None:
            return Response({"detail": "Appointment not found."}, status=404)

        serializer = RequestOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        request_otp(appointment, purpose=serializer.validated_data["purpose"])
        return Response({"detail": "Verification code sent."}, status=200)


class CancelAppointmentView(APIView):
    """PATCH /appointments/{id}/cancel
    OTP required unless the request is from an authenticated staff user."""
    permission_classes = [AllowAny]

    def patch(self, request, pk):
        appointment = _get_appointment_or_404(pk)
        if appointment is None:
            return Response({"detail": "Appointment not found."}, status=404)

        serializer = CancelAppointmentSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        is_staff_request = request.user.is_authenticated

        try:
            if not is_staff_request:
                verify_otp(appointment, purpose="cancel", code=data["otp_code"])

            updated = cancel_appointment(
                appointment_id=appointment.id,
                reason=data["reason"],
                performed_by_user=request.user if is_staff_request else None,
            )
        except BookingError as e:
            return Response({"detail": str(e)}, status=400)

        return Response(AppointmentSerializer(updated).data)


class RescheduleAppointmentView(APIView):
    """PATCH /appointments/{id}/reschedule
    OTP required unless the request is from an authenticated staff user."""
    permission_classes = [AllowAny]

    def patch(self, request, pk):
        appointment = _get_appointment_or_404(pk)
        if appointment is None:
            return Response({"detail": "Appointment not found."}, status=404)

        serializer = RescheduleAppointmentSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        is_staff_request = request.user.is_authenticated

        try:
            if not is_staff_request:
                verify_otp(appointment, purpose="reschedule", code=data["otp_code"])

            updated = reschedule_appointment(
                appointment_id=appointment.id,
                new_date=data["new_date"],
                new_start_time=data["new_start_time"],
                performed_by_user=request.user if is_staff_request else None,
            )
        except (BookingError, SlotUnavailableError) as e:
            return Response({"detail": str(e)}, status=400)

        return Response(AppointmentSerializer(updated).data)
    

class PatientAppointmentsView(APIView):
    """GET /patients/{id}/appointments/
    Staff-only (authenticated User via token auth). Not exposed to patients —
    see README, System Design, for why this isn't a public/patient-facing endpoint."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            patient = Patient.objects.get(pk=pk)
        except Patient.DoesNotExist:
            return Response({"detail": "Patient not found."}, status=404)

        upcoming = (
            Appointment.objects.filter(
                patient=patient,
                status=Appointment.Status.BOOKED,
                date__gte=date_cls.today(),
            )
            .select_related("doctor", "patient")
            .order_by("date", "start_time")
        )

        return Response(AppointmentSerializer(upcoming, many=True).data)
    
