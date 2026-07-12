from datetime import date, timedelta

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
)


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