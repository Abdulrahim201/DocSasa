from datetime import date as date_cls

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from appointments.serializers import AvailabilityQuerySerializer, SlotSerializer
from appointments.services import get_available_slots

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