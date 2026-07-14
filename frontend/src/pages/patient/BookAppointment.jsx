import { useState, useEffect } from "react";
import { api } from "../../api/client";

export default function BookAppointment() {
  const [doctors, setDoctors] = useState([]);
  const [doctorId, setDoctorId] = useState("");
  const [date, setDate] = useState("");
  const [slots, setSlots] = useState([]);
  const [selectedSlot, setSelectedSlot] = useState(null);
  const [form, setForm] = useState({ name: "", email: "", phone: "" });
  const [status, setStatus] = useState({ loading: false, error: null, result: null });

  useEffect(() => {
    api.get("/doctors/").then(setDoctors).catch((e) => setStatus((s) => ({ ...s, error: e.message })));
  }, []);

  useEffect(() => {
    if (!doctorId || !date) {
      setSlots([]);
      return;
    }
    setSelectedSlot(null);
    api
      .get(`/doctors/${doctorId}/availability/?date=${date}`)
      .then(setSlots)
      .catch((e) => setStatus((s) => ({ ...s, error: e.message })));
  }, [doctorId, date]);

  async function handleBook(e) {
    e.preventDefault();
    setStatus({ loading: true, error: null, result: null });
    try {
      const appointment = await api.post("/appointments/", {
        doctor: Number(doctorId),
        date,
        start_time: selectedSlot.start_time,
        patient_name: form.name,
        patient_email: form.email,
        patient_phone: form.phone,
      });
      setStatus({ loading: false, error: null, result: appointment });
    } catch (err) {
      setStatus({ loading: false, error: err.message, result: null });
    }
  }

  if (status.result) {
    const manageUrl = `/appointments/${status.result.id}`;
    return (
      <div className="max-w-md mx-auto mt-16 p-6 bg-white rounded-lg shadow">
        <h1 className="text-xl font-semibold mb-2">Appointment booked</h1>
        <p className="text-gray-600 mb-4">
          A confirmation has been sent to {status.result.patient.email}. You can manage this
          appointment any time at:
        </p>

         <a href={manageUrl}
        className="block bg-blue-50 text-blue-700 p-3 rounded text-sm break-all underline"
    >Cancel/Reschedule Appointment</a>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto mt-16 p-6 bg-white rounded-lg shadow">
      <h1 className="text-xl font-semibold mb-4">Book an appointment</h1>

      <label className="block text-sm font-medium mb-1">Doctor</label>
      <select
        className="w-full border rounded p-2 mb-4"
        value={doctorId}
        onChange={(e) => setDoctorId(e.target.value)}
      >
        <option value="">Select a doctor</option>
        {doctors.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name} {d.specialty && `— ${d.specialty}`}
          </option>
        ))}
      </select>

      <label className="block text-sm font-medium mb-1">Date</label>
      <input
        type="date"
        min={new Date().toISOString().split("T")[0]}
        className="w-full border rounded p-2 mb-4"
        value={date}
        onChange={(e) => setDate(e.target.value)}
      />

      {doctorId && date && (
        <>
          <label className="block text-sm font-medium mb-1">Available slots</label>
          {slots.length === 0 ? (
            <p className="text-sm text-gray-500 mb-4">No slots available on this date.</p>
          ) : (
            <div className="grid grid-cols-3 gap-2 mb-4">
              {slots.map((slot) => (
                <button
                  key={slot.start_time}
                  type="button"
                  onClick={() => setSelectedSlot(slot)}
                  className={`text-sm py-1 px-2 rounded border ${
                    selectedSlot?.start_time === slot.start_time
                      ? "bg-blue-600 text-white border-blue-600"
                      : "bg-white text-gray-700"
                  }`}
                >
                  {slot.start_time.slice(0, 5)}
                </button>
              ))}
            </div>
          )}
        </>
      )}

      {selectedSlot && (
        <form onSubmit={handleBook}>
          <input
            required
            placeholder="Full name"
            className="w-full border rounded p-2 mb-2"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <input
            required
            type="email"
            placeholder="Email"
            className="w-full border rounded p-2 mb-2"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
          <input
            placeholder="Phone (optional)"
            className="w-full border rounded p-2 mb-4"
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
          />
          {status.error && <p className="text-red-600 text-sm mb-2">{status.error}</p>}
          <button
            type="submit"
            disabled={status.loading}
            className="w-full bg-blue-600 text-white rounded p-2 font-medium"
          >
            {status.loading ? "Booking…" : "Book appointment"}
          </button>
        </form>
      )}

      <div className="mt-6 text-center text-sm">
        <a href="/staff/login" className="text-gray-500 underline">
          Staff login
        </a>
      </div>
    </div>
  );
}