import { useState, useEffect } from "react";
import { api } from "../../api/client";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export default function Doctors() {
  const [doctors, setDoctors] = useState([]);
  const [newDoctor, setNewDoctor] = useState({ name: "", specialty: "" });
  const [hoursForm, setHoursForm] = useState({});
  const [error, setError] = useState(null);

  function load() {
    api.get("/doctors/").then(setDoctors).catch((e) => setError(e.message));
  }

  useEffect(load, []);

  async function handleCreateDoctor(e) {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/doctors/", newDoctor, { auth: true });
      setNewDoctor({ name: "", specialty: "" });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleSetHours(doctorId) {
    const form = hoursForm[doctorId];
    if (!form?.weekday && form?.weekday !== 0) return;
    setError(null);
    try {
      await api.post(
        `/doctors/${doctorId}/working-hours/`,
        {
          weekday: Number(form.weekday),
          start_time: form.start_time,
          end_time: form.end_time,
        },
        { auth: true }
      );
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  function updateHoursForm(doctorId, field, value) {
    setHoursForm({
      ...hoursForm,
      [doctorId]: { ...hoursForm[doctorId], [field]: value },
    });
  }

  async function handleSetAllWeekdays(doctorId) {
        const form = hoursForm[doctorId];
        if (!form?.start_time || !form?.end_time) {
        setError("Please enter a start and end time before applying to all weekdays.");
            return;
        }
        setError(null);
            try {
            // Monday(0) through Friday(4) — a common default. Sat/Sun (5, 6) are
            // left alone here since "every day" usually means weekdays in practice;
            // staff can still set Sat/Sun individually via the single-day form below.
            await Promise.all(
                [0, 1, 2, 3, 4].map((weekday) =>
                api.post(
                `/doctors/${doctorId}/working-hours/`,
                { weekday, start_time: form.start_time, end_time: form.end_time },
                { auth: true }
                )
                    )
            );
            load();
            } catch (err) {
                setError(err.message);
                    }
    }   

  return (
    <div className="max-w-3xl mx-auto mt-10 p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-xl font-semibold">Doctors</h1>
        <a href="/staff/dashboard" className="text-blue-600 underline text-sm">
          Back to appointments
        </a>
      </div>

      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}

      <form onSubmit={handleCreateDoctor} className="flex gap-2 mb-8">
        <input
          required
          placeholder="Doctor name"
          className="border rounded p-2 flex-1"
          value={newDoctor.name}
          onChange={(e) => setNewDoctor({ ...newDoctor, name: e.target.value })}
        />
        <input
          placeholder="Specialty"
          className="border rounded p-2 flex-1"
          value={newDoctor.specialty}
          onChange={(e) => setNewDoctor({ ...newDoctor, specialty: e.target.value })}
        />
        <button type="submit" className="bg-blue-600 text-white rounded px-4">
          Add doctor
        </button>
      </form>

      {doctors.map((doc) => (
        <div key={doc.id} className="bg-white rounded shadow p-4 mb-4">
          <h2 className="font-medium mb-2">
            {doc.name} {doc.specialty && `— ${doc.specialty}`}
          </h2>

          <ul className="text-sm text-gray-600 mb-3">
            {doc.working_hours.length === 0 && <li>No hours set — off every day.</li>}
            {doc.working_hours.map((wh) => (
              <li key={wh.id}>
                {wh.weekday_label}: {wh.start_time.slice(0, 5)}–{wh.end_time.slice(0, 5)}
              </li>
            ))}
          </ul>

          <div className="flex gap-2 items-center">
            <select
              className="border rounded p-1 text-sm"
              value={hoursForm[doc.id]?.weekday ?? ""}
              onChange={(e) => updateHoursForm(doc.id, "weekday", e.target.value)}
            >
              <option value="">Weekday</option>
              {WEEKDAYS.map((label, i) => (
                <option key={i} value={i}>
                  {label}
                </option>
              ))}
            </select>
            <input
              type="time"
              className="border rounded p-1 text-sm"
              value={hoursForm[doc.id]?.start_time ?? ""}
              onChange={(e) => updateHoursForm(doc.id, "start_time", e.target.value)}
            />
            <input
              type="time"
              className="border rounded p-1 text-sm"
              value={hoursForm[doc.id]?.end_time ?? ""}
              onChange={(e) => updateHoursForm(doc.id, "end_time", e.target.value)}
            />
            <button
              onClick={() => handleSetHours(doc.id)}
              className="bg-gray-800 text-white rounded px-3 py-1 text-sm"
            >
              Set
            </button>
            <button
                onClick={() => handleSetAllWeekdays(doc.id)}
                className="bg-blue-600 text-white rounded px-3 py-1 text-sm"
                >
                Apply Mon–Fri
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}