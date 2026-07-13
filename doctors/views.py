from datetime import date as date_cls

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated

from appointments.serializers import AvailabilityQuerySerializer, SlotSerializer
from appointments.services import get_available_slots
from .serializers import DoctorSerializer, WorkingHoursSerializer

from .models import Doctor


class DoctorAvailabilityView(APIView):
    """GET /doctors/{id}/availability?date=YYYY-MM-DD
    Public — no login required, since patients use this to browse slots."""
    permission_classes = [AllowAny]

    def get(self, request, pk):
        try:
            doctor = Doctor.objects.get(pk=pk)
        except Doctor.DoesNotExist:
            return Response({"detail": "Doctor not found."}, status=404)

        query = AvailabilityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        slots = get_available_slots(doctor, query.validated_data["date"])
        return Response(SlotSerializer(slots, many=True).data)
    

class DoctorListCreateView(ListCreateAPIView):
    """GET /doctors/ — public, patients need this to pick a doctor to book with.
    POST /doctors/ — staff-only, adding a new doctor."""
    queryset = Doctor.objects.all().prefetch_related("working_hours")
    serializer_class = DoctorSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return [AllowAny()]


class DoctorDetailView(RetrieveUpdateAPIView):
    """GET /doctors/{id}/ — public.
    PATCH/PUT /doctors/{id}/ — staff-only, editing a doctor's name/specialty."""
    queryset = Doctor.objects.all().prefetch_related("working_hours")
    serializer_class = DoctorSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [IsAuthenticated()]
        return [AllowAny()]


class DoctorWorkingHoursView(APIView):
    """POST /doctors/{id}/working-hours/ — staff-only. Upserts a single
    weekday's hours: creates it if the doctor has no row for that weekday yet,
    otherwise updates the existing one. Matches the unique_doctor_weekday
    constraint — a doctor can only have one row per weekday."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            doctor = Doctor.objects.get(pk=pk)
        except Doctor.DoesNotExist:
            return Response({"detail": "Doctor not found."}, status=404)

        weekday = request.data.get("weekday")
        existing = WorkingHours.objects.filter(doctor=doctor, weekday=weekday).first()

        serializer = WorkingHoursSerializer(instance=existing, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(doctor=doctor)

        return Response(serializer.data, status=200 if existing else 201)

    def delete(self, request, pk):
        """DELETE /doctors/{id}/working-hours/?weekday=N — remove a day
        entirely, marking the doctor as off that day (no row = day off)."""
        weekday = request.query_params.get("weekday")
        deleted, _ = WorkingHours.objects.filter(doctor_id=pk, weekday=weekday).delete()
        if not deleted:
            return Response({"detail": "No working hours found for that weekday."}, status=404)
        return Response(status=204)