import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";

export default function ManageAppointment() {
  const { id } = useParams();
  const [appointment, setAppointment] = useState(null);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState(null); // "cancel" | "reschedule" | null
  const [otpRequested, setOtpRequested] = useState(false);
  const [otpCode, setOtpCode] = useState("");
  const [reason, setReason] = useState("");
  const [newDate, setNewDate] = useState("");
  const [slots, setSlots] = useState([]);
  const [newSlot, setNewSlot] = useState(null);
  const [success, setSuccess] = useState(null);

  // Fetch the appointment itself once, on load.
  useEffect(() => {
    api
      .get(`/appointments/${id}/`)
      .then(setAppointment)
      .catch((e) => setError(e.message));
  }, [id]);

  // Fetch availability whenever the reschedule date changes, once we know
  // which doctor this appointment belongs to.
  useEffect(() => {
    if (!appointment || !newDate) {
      setSlots([]);
      return;
    }
    setNewSlot(null);
    api
      .get(`/doctors/${appointment.doctor}/availability/?date=${newDate}`)
      .then(setSlots)
      .catch((e) => setError(e.message));
  }, [newDate, appointment]);

  async function requestOtp(purpose) {
    setError(null);
    try {
      await api.post(`/appointments/${id}/request-otp/`, { purpose });
      setOtpRequested(true);
      setMode(purpose);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleCancel(e) {
    e.preventDefault();
    setError(null);
    try {
      const result = await api.patch(`/appointments/${id}/cancel/`, {
        reason,
        otp_code: otpCode,
      });
      setSuccess(result);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleReschedule(e) {
    e.preventDefault();
    setError(null);
    try {
      const result = await api.patch(`/appointments/${id}/reschedule/`, {
        new_date: newDate,
        new_start_time: newSlot.start_time,
        otp_code: otpCode,
      });
      setSuccess(result);
    } catch (err) {
      setError(err.message);
    }
  }

  if (success) {
    return (
      <div className="max-w-md mx-auto mt-16 p-6 bg-white rounded-lg shadow">
        <h1 className="text-xl font-semibold mb-2">
          {success.status === "cancelled" ? "Appointment cancelled" : "Appointment rescheduled"}
        </h1>
        <p className="text-gray-600">
          {success.status === "cancelled"
            ? "This slot has been freed up."
            : `New time: ${success.date} at ${success.start_time.slice(0, 5)}.`}
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto mt-16 p-6 bg-white rounded-lg shadow">
      <h1 className="text-xl font-semibold mb-4">Manage your appointment</h1>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      {appointment && (
        <div className="bg-gray-50 rounded p-3 mb-4 text-sm">
          <p><span className="font-medium">Patient:</span> {appointment.patient.name}</p>
          <p><span className="font-medium">Doctor:</span> {appointment.doctor_name}</p>
          <p><span className="font-medium">Date:</span> {appointment.date}</p>
          <p><span className="font-medium">Time:</span> {appointment.start_time.slice(0, 5)}</p>
          <p>
            <span className="font-medium">Status:</span>{" "}
            <span className="capitalize">{appointment.status}</span>
          </p>
        </div>
      )}

      {!mode && appointment?.status === "booked" && (
        <div className="flex gap-2">
          <button
            onClick={() => requestOtp("cancel")}
            className="flex-1 bg-red-600 text-white rounded p-2"
          >
            Cancel appointment
          </button>
          <button
            onClick={() => requestOtp("reschedule")}
            className="flex-1 bg-blue-600 text-white rounded p-2"
          >
            Reschedule
          </button>
        </div>
      )}

      {appointment?.status === "cancelled" && !mode && (
        <p className="text-sm text-gray-500">This appointment has already been cancelled.</p>
      )}

      {mode && otpRequested && (
        <p className="text-sm text-gray-600 mb-4 mt-4">
          A verification code has been sent to your email. Enter it below to continue.
        </p>
      )}

      {mode === "cancel" && (
        <form onSubmit={handleCancel}>
          <input
            required
            placeholder="Reason for cancelling"
            className="w-full border rounded p-2 mb-2"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <input
            required
            placeholder="Verification code"
            className="w-full border rounded p-2 mb-4"
            value={otpCode}
            onChange={(e) => setOtpCode(e.target.value)}
          />
          <button type="submit" className="w-full bg-red-600 text-white rounded p-2">
            Confirm cancellation
          </button>
        </form>
      )}

      {mode === "reschedule" && (
        <form onSubmit={handleReschedule}>
          <input
            type="date"
            required
            min={new Date().toISOString().split("T")[0]}
            className="w-full border rounded p-2 mb-2"
            value={newDate}
            onChange={(e) => setNewDate(e.target.value)}
          />
          {newDate && slots.length === 0 && (
            <p className="text-sm text-gray-500 mb-2">No slots available on this date.</p>
          )}
          {slots.length > 0 && (
            <div className="grid grid-cols-3 gap-2 mb-2">
              {slots.map((slot) => (
                <button
                  type="button"
                  key={slot.start_time}
                  onClick={() => setNewSlot(slot)}
                  className={`text-sm py-1 rounded border ${
                    newSlot?.start_time === slot.start_time
                      ? "bg-blue-600 text-white"
                      : "bg-white"
                  }`}
                >
                  {slot.start_time.slice(0, 5)}
                </button>
              ))}
            </div>
          )}
          <input
            required
            placeholder="Verification code"
            className="w-full border rounded p-2 mb-4"
            value={otpCode}
            onChange={(e) => setOtpCode(e.target.value)}
          />
          <button
            type="submit"
            disabled={!newSlot}
            className={`w-full rounded p-2 text-white ${
              newSlot ? "bg-blue-600" : "bg-gray-300 cursor-not-allowed"
            }`}
          >
            Confirm reschedule
          </button>
        </form>
      )}
    </div>
  );
}