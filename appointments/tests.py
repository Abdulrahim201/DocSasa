from datetime import date, time, timedelta

from django.test import TestCase
from django.db import IntegrityError, transaction
from django.utils import timezone

from doctors.models import Doctor, WorkingHours
from .models import Appointment, Patient
from .services import (
    get_available_slots,
    book_appointment,
    cancel_appointment,
    reschedule_appointment,
    BookingError,
    SlotUnavailableError,
    request_otp, 
)

from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

User = get_user_model()


def next_weekday(weekday):
    """Return the next date (strictly after today) falling on the given weekday
    (0=Monday ... 6=Sunday), so tests don't depend on what day they're run."""
    today = date.today()
    days_ahead = (weekday - today.weekday()) % 7
    return today + timedelta(days=days_ahead or 7)


class AvailabilityTests(TestCase):
    def setUp(self):
        self.doctor = Doctor.objects.create(name="Dr. Test", specialty="General")
        WorkingHours.objects.create(
            doctor=self.doctor, weekday=0,  # Monday
            start_time="09:00", end_time="17:00",
        )
        self.monday = next_weekday(0)

    def test_generates_correct_slot_count(self):
        slots = get_available_slots(self.doctor, self.monday)
        self.assertEqual(len(slots), 16)  # 8 hours / 30 min
        self.assertEqual(slots[0]["start_time"].strftime("%H:%M"), "09:00")
        self.assertEqual(slots[-1]["end_time"].strftime("%H:%M"), "17:00")

    def test_returns_empty_on_doctors_day_off(self):
        tuesday = next_weekday(1)
        self.assertEqual(get_available_slots(self.doctor, tuesday), [])

    def test_booked_slot_is_excluded(self):
        slots = get_available_slots(self.doctor, self.monday)
        book_appointment(
            doctor=self.doctor, date=self.monday, start_time=slots[0]["start_time"],
            patient_name="Jane", patient_email="jane@example.com",
        )
        remaining = get_available_slots(self.doctor, self.monday)
        self.assertEqual(len(remaining), 15)
        self.assertNotIn(slots[0]["start_time"], [s["start_time"] for s in remaining])

    def test_dangling_remainder_not_offered(self):
        # 09:00-09:45 should yield exactly one 30-min slot, not a partial second one.
        doctor2 = Doctor.objects.create(name="Dr. Partial")
        WorkingHours.objects.create(
            doctor=doctor2, weekday=0, start_time="09:00", end_time="09:45",
        )
        slots = get_available_slots(doctor2, self.monday)
        self.assertEqual(len(slots), 1)

    def test_past_date_returns_no_slots(self):
        from datetime import timedelta
        yesterday = date.today() - timedelta(days=1)
        self.assertEqual(get_available_slots(self.doctor, yesterday), [])


class BookAppointmentTests(TestCase):
    def setUp(self):
        self.doctor = Doctor.objects.create(name="Dr. Test")
        WorkingHours.objects.create(
            doctor=self.doctor, weekday=0, start_time="09:00", end_time="17:00",
        )
        self.monday = next_weekday(0)
        self.slots = get_available_slots(self.doctor, self.monday)

    def test_book_appointment_success(self):
        appt = book_appointment(
            doctor=self.doctor, date=self.monday, start_time=self.slots[0]["start_time"],
            patient_name="Jane Doe", patient_email="jane@example.com",
        )
        self.assertEqual(appt.status, Appointment.Status.BOOKED)
        self.assertEqual(appt.patient.name, "Jane Doe")

    def test_book_same_slot_twice_rejected(self):
        book_appointment(
            doctor=self.doctor, date=self.monday, start_time=self.slots[0]["start_time"],
            patient_name="Jane", patient_email="jane@example.com",
        )
        with self.assertRaises(SlotUnavailableError):
            book_appointment(
                doctor=self.doctor, date=self.monday, start_time=self.slots[0]["start_time"],
                patient_name="John", patient_email="john@example.com",
            )

    def test_book_outside_working_hours_rejected(self):
        with self.assertRaises(SlotUnavailableError):
            book_appointment(
                doctor=self.doctor, date=self.monday, start_time="20:00",
                patient_name="Jane", patient_email="jane@example.com",
            )

    def test_book_on_doctors_day_off_rejected(self):
        tuesday = next_weekday(1)
        with self.assertRaises(SlotUnavailableError):
            book_appointment(
                doctor=self.doctor, date=tuesday, start_time="09:00",
                patient_name="Jane", patient_email="jane@example.com",
            )

    def test_repeat_patient_reuses_existing_record(self):
        book_appointment(
            doctor=self.doctor, date=self.monday, start_time=self.slots[0]["start_time"],
            patient_name="Jane Doe", patient_email="jane@example.com",
        )
        book_appointment(
            doctor=self.doctor, date=self.monday, start_time=self.slots[1]["start_time"],
            patient_name="Jane Doe", patient_email="jane@example.com",
        )
        self.assertEqual(Patient.objects.filter(email="jane@example.com").count(), 1)

    def test_unique_constraint_enforced_at_database_level(self):
        """Bypass the service layer entirely and hit the model directly —
        proves the DB constraint itself is the real guarantee, not just
        application-level logic that could have a bug."""
        patient = Patient.objects.create(name="A", email="a@example.com")
        Appointment.objects.create(
            doctor=self.doctor, patient=patient, date=self.monday,
            start_time="09:00", end_time="09:30",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Appointment.objects.create(
                    doctor=self.doctor, patient=patient, date=self.monday,
                    start_time="09:00", end_time="09:30",
                )


class CancelAppointmentTests(TestCase):
    def setUp(self):
        self.doctor = Doctor.objects.create(name="Dr. Test")
        WorkingHours.objects.create(
            doctor=self.doctor, weekday=0, start_time="09:00", end_time="17:00",
        )
        self.monday = next_weekday(0)
        slots = get_available_slots(self.doctor, self.monday)
        self.appt = book_appointment(
            doctor=self.doctor, date=self.monday, start_time=slots[0]["start_time"],
            patient_name="Jane", patient_email="jane@example.com",
        )

    def test_cancel_success(self):
        cancelled = cancel_appointment(appointment_id=self.appt.id, reason="Can't make it")
        self.assertEqual(cancelled.status, Appointment.Status.CANCELLED)
        self.assertEqual(cancelled.cancellation_reason, "Can't make it")

    def test_cancel_requires_reason(self):
        with self.assertRaises(BookingError):
            cancel_appointment(appointment_id=self.appt.id, reason="")

    def test_cancel_already_cancelled_rejected(self):
        cancel_appointment(appointment_id=self.appt.id, reason="First cancel")
        with self.assertRaises(BookingError):
            cancel_appointment(appointment_id=self.appt.id, reason="Second cancel")

    def test_cancelled_slot_becomes_available_again(self):
        slot_time = self.appt.start_time
        cancel_appointment(appointment_id=self.appt.id, reason="Freeing this up")
        available = get_available_slots(self.doctor, self.monday)
        self.assertIn(slot_time, [s["start_time"] for s in available])


class RescheduleAppointmentTests(TestCase):
    def setUp(self):
        self.doctor = Doctor.objects.create(name="Dr. Test")
        WorkingHours.objects.create(
            doctor=self.doctor, weekday=0, start_time="09:00", end_time="17:00",
        )
        self.monday = next_weekday(0)
        self.slots = get_available_slots(self.doctor, self.monday)
        self.appt = book_appointment(
            doctor=self.doctor, date=self.monday, start_time=self.slots[0]["start_time"],
            patient_name="Jane", patient_email="jane@example.com",
        )

    def test_reschedule_success(self):
        moved = reschedule_appointment(
            appointment_id=self.appt.id, new_date=self.monday,
            new_start_time=self.slots[3]["start_time"],
        )
        self.assertEqual(moved.start_time, self.slots[3]["start_time"])
        self.assertEqual(moved.status, Appointment.Status.BOOKED)

    def test_reschedule_frees_original_slot(self):
        original_start = self.appt.start_time
        reschedule_appointment(
            appointment_id=self.appt.id, new_date=self.monday,
            new_start_time=self.slots[3]["start_time"],
        )
        available = get_available_slots(self.doctor, self.monday)
        self.assertIn(original_start, [s["start_time"] for s in available])

    def test_reschedule_to_taken_slot_rejected_and_original_untouched(self):
        other_patient_slot = self.slots[3]["start_time"]
        book_appointment(
            doctor=self.doctor, date=self.monday, start_time=other_patient_slot,
            patient_name="Other Patient", patient_email="other@example.com",
        )
        original_start = self.appt.start_time

        with self.assertRaises(SlotUnavailableError):
            reschedule_appointment(
                appointment_id=self.appt.id, new_date=self.monday,
                new_start_time=other_patient_slot,
            )

        # Confirms the transaction rolled back — the patient did not lose
        # their original slot when the new one turned out to be taken.
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.start_time, original_start)
        self.assertEqual(self.appt.status, Appointment.Status.BOOKED)

    def test_reschedule_cancelled_appointment_rejected(self):
        cancel_appointment(appointment_id=self.appt.id, reason="No longer needed")
        with self.assertRaises(BookingError):
            reschedule_appointment(
                appointment_id=self.appt.id, new_date=self.monday,
                new_start_time=self.slots[5]["start_time"],
            )



class AppointmentAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.doctor = Doctor.objects.create(name="Dr. API Test")
        WorkingHours.objects.create(
            doctor=self.doctor, weekday=0, start_time="09:00", end_time="17:00",
        )
        self.monday = next_weekday(0)
        self.staff_user = User.objects.create_user(username="reception1", password="testpass123")

    def test_book_appointment_via_api_unauthenticated(self):
        response = self.client.post("/api/v1/appointments/", {
            "doctor": self.doctor.id, "date": str(self.monday), "start_time": "09:00:00",
            "patient_name": "Jane", "patient_email": "jane@example.com",
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "booked")
        self.assertIsNone(response.data["booked_by"])

    def test_list_appointments_requires_authentication(self):
        response = self.client.get("/api/v1/appointments/")
        self.assertEqual(response.status_code, 401)

    def test_list_appointments_succeeds_for_authenticated_staff(self):
        
        appt = book_appointment(
                doctor=self.doctor, date=self.monday, start_time=time(9, 0),
                patient_name="Jane", patient_email="jane@example.com",
            )
       
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.get("/api/v1/appointments/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_cancel_without_otp_rejected_for_anonymous_patient(self):
        appt = book_appointment(
            doctor=self.doctor, date=self.monday, start_time=time(9, 0),
            patient_name="Jane", patient_email="jane@example.com",
            )
      
        response = self.client.patch(
            f"/api/v1/appointments/{appt.id}/cancel/",
            {"reason": "Testing"}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("otp_code", response.data)

    def test_cancel_with_valid_otp_succeeds(self):
        appt = book_appointment(
            doctor=self.doctor, date=self.monday, start_time=time(9, 0),
            patient_name="Jane", patient_email="jane@example.com",
        )
        otp = request_otp(appt, purpose="cancel")
        response = self.client.patch(
            f"/api/v1/appointments/{appt.id}/cancel/",
            {"reason": "Testing", "otp_code": otp.code}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "cancelled")

    def test_cancel_by_authenticated_staff_skips_otp(self):
        appt = book_appointment(
            doctor=self.doctor, date=self.monday, start_time=time(9, 0),
            patient_name="Jane", patient_email="jane@example.com",
        )
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.patch(
            f"/api/v1/appointments/{appt.id}/cancel/",
            {"reason": "Staff cancelled this"}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "cancelled")

    def test_get_appointment_detail_is_public(self):
        appt = book_appointment(
        doctor=self.doctor, date=self.monday, start_time=time(9, 0),
        patient_name="Jane", patient_email="jane@example.com",
        )
        response = self.client.get(f"/api/v1/appointments/{appt.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(appt.id))

    def test_get_nonexistent_appointment_returns_404(self):
        import uuid
        response = self.client.get(f"/api/v1/appointments/{uuid.uuid4()}/")
        self.assertEqual(response.status_code, 404)


class DoctorAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.staff_user = User.objects.create_user(username="reception2", password="testpass123")

    def test_list_doctors_is_public(self):
        Doctor.objects.create(name="Dr. Public Test")
        response = self.client.get("/api/v1/doctors/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_create_doctor_requires_authentication(self):
        response = self.client.post("/api/v1/doctors/", {"name": "Dr. Blocked"})
        self.assertEqual(response.status_code, 401)

    def test_create_doctor_succeeds_for_staff(self):
        self.client.force_authenticate(user=self.staff_user)
        response = self.client.post("/api/v1/doctors/", {"name": "Dr. Allowed", "specialty": "ENT"})
        self.assertEqual(response.status_code, 201)

    def test_set_working_hours_requires_authentication(self):
        doctor = Doctor.objects.create(name="Dr. Hours Test")
        response = self.client.post(
            f"/api/v1/doctors/{doctor.id}/working-hours/",
            {"weekday": 0, "start_time": "09:00", "end_time": "17:00"}, format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_set_working_hours_upserts_same_weekday(self):
        doctor = Doctor.objects.create(name="Dr. Hours Test")
        self.client.force_authenticate(user=self.staff_user)

        first = self.client.post(
            f"/api/v1/doctors/{doctor.id}/working-hours/",
            {"weekday": 0, "start_time": "09:00", "end_time": "17:00"}, format="json",
        )
        second = self.client.post(
            f"/api/v1/doctors/{doctor.id}/working-hours/",
            {"weekday": 0, "start_time": "10:00", "end_time": "16:00"}, format="json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["id"], second.data["id"])  # same row, not a duplicate
        self.assertEqual(WorkingHours.objects.filter(doctor=doctor, weekday=0).count(), 1)

