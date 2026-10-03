// SessionMind AI demo front end. Plain JS, no build step, no framework --
// every function here just calls one of the real endpoints in server.py,
// which in turn call the real AWS Events API / AWS Knowledge MCP server.

const state = {
  sessions: [],
  scheduleIds: new Set(),
  notes: [],
};

const el = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const resp = await fetch(path, {
    method: options.method || "GET",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const data = await resp.json();
      detail = data.message || data.detail || JSON.stringify(data);
    } catch {
      // ignore parse failure, keep the plain status text
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

function setStatus(elementId, message, isError = false) {
  const node = el(elementId);
  node.textContent = message;
  node.classList.toggle("status--error", isError);
}

function formatSessionMeta(session) {
  const bits = [session.abbreviation, session.level, session.room, session.start].filter(Boolean);
  return bits.join(" · ");
}

// ---------------------------------------------------------------------------
// Step 1: events
// ---------------------------------------------------------------------------

async function loadEvents() {
  const select = el("event-select");
  try {
    const events = await api("/api/events");
    select.innerHTML = "";
    if (events.length === 0) {
      select.innerHTML = '<option value="">No public events currently listed</option>';
      setStatus("event-select-status", "The real ListEvents call returned no public (no-registration) events right now.");
      return;
    }
    for (const event of events) {
      const option = document.createElement("option");
      option.value = event.eventId;
      option.textContent = `${event.name} (${event.eventId})`;
      select.appendChild(option);
    }
    el("load-event-btn").disabled = false;
    setStatus("event-select-status", `${events.length} real public event(s) loaded from GET /v1/events.`);
  } catch (err) {
    setStatus("event-select-status", `Failed to load events: ${err.message}`, true);
  }
}

async function selectEvent() {
  const eventId = el("event-select").value;
  if (!eventId) return;
  setStatus("event-select-status", "Calling real ListSessions… this can take a few seconds for a large catalog.");
  el("load-event-btn").disabled = true;
  try {
    const result = await api(`/api/events/${encodeURIComponent(eventId)}/select`, { method: "POST" });
    setStatus("event-select-status", `Loaded ${result.sessionCount} real sessions from ${eventId}.`);
    state.scheduleIds = new Set();
    state.notes = [];
    await refreshSessions();
    renderSchedule();
    renderNotes();
    el("notes-panel").hidden = false;
    el("reports-panel").hidden = false;
  } catch (err) {
    setStatus("event-select-status", `Failed to load sessions: ${err.message}`, true);
  } finally {
    el("load-event-btn").disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Step 2: session catalog
// ---------------------------------------------------------------------------

async function refreshSessions() {
  state.sessions = await api("/api/sessions");
  renderSessionList();
  renderNoteSessionOptions();
}

function renderSessionList() {
  const filterText = el("session-filter").value.trim().toLowerCase();
  const list = el("session-list");
  list.innerHTML = "";

  const filtered = filterText
    ? state.sessions.filter((s) => s.title.toLowerCase().includes(filterText))
    : state.sessions;

  if (filtered.length === 0) {
    list.innerHTML = '<li class="status">No sessions match.</li>';
    return;
  }

  for (const session of filtered) {
    const li = document.createElement("li");
    li.className = "session-card";

    const title = document.createElement("p");
    title.className = "session-card__title";
    title.textContent = session.title;
    li.appendChild(title);

    const meta = document.createElement("p");
    meta.className = "session-card__meta";
    meta.textContent = formatSessionMeta(session) || "No scheduled time published yet";
    li.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "session-card__actions";

    const prepBtn = document.createElement("button");
    prepBtn.type = "button";
    prepBtn.className = "btn";
    prepBtn.textContent = "View prep card";
    prepBtn.addEventListener("click", () => showPrepCard(session.sessionId));
    actions.appendChild(prepBtn);

    const scheduleBtn = document.createElement("button");
    scheduleBtn.type = "button";
    scheduleBtn.className = "btn btn--primary";
    const inSchedule = state.scheduleIds.has(session.sessionId);
    scheduleBtn.textContent = inSchedule ? "✓ In my schedule" : "Add to my schedule";
    scheduleBtn.disabled = inSchedule;
    scheduleBtn.addEventListener("click", () => addToSchedule(session.sessionId));
    actions.appendChild(scheduleBtn);

    li.appendChild(actions);
    list.appendChild(li);
  }
}

async function showPrepCard(sessionId) {
  const dialog = el("prep-card-dialog");
  const bulletsList = el("prep-card-bullets");
  bulletsList.innerHTML = "";
  setStatus("prep-card-status", "Calling real GetSession + the AWS Knowledge MCP server…");
  dialog.showModal();

  try {
    const card = await api(`/api/sessions/${encodeURIComponent(sessionId)}/prep-card`);
    setStatus("prep-card-status", `Prep card for "${card.title}" (Knowledge MCP query: "${card.docQuery}")`);
    for (const bullet of card.bullets) {
      const li = document.createElement("li");
      li.textContent = bullet;
      bulletsList.appendChild(li);
    }
  } catch (err) {
    setStatus("prep-card-status", `Failed to build prep card: ${err.message}`, true);
  }
}

// ---------------------------------------------------------------------------
// Step 3: schedule
// ---------------------------------------------------------------------------

async function addToSchedule(sessionId) {
  try {
    const result = await api(`/api/sessions/${encodeURIComponent(sessionId)}/schedule`, { method: "POST" });
    state.scheduleIds = new Set(result.scheduleSessionIds);
    renderSessionList();
    renderSchedule();
    renderNoteSessionOptions();
  } catch (err) {
    setStatus("event-select-status", `Failed to add to schedule: ${err.message}`, true);
  }
}

async function removeFromSchedule(sessionId) {
  try {
    const result = await api(`/api/sessions/${encodeURIComponent(sessionId)}/schedule`, { method: "DELETE" });
    state.scheduleIds = new Set(result.scheduleSessionIds);
    renderSessionList();
    renderSchedule();
    renderNoteSessionOptions();
  } catch (err) {
    setStatus("event-select-status", `Failed to remove from schedule: ${err.message}`, true);
  }
}

function renderSchedule() {
  const list = el("schedule-list");
  const emptyMsg = el("schedule-empty");
  list.innerHTML = "";

  const scheduled = state.sessions.filter((s) => state.scheduleIds.has(s.sessionId));
  emptyMsg.hidden = scheduled.length > 0;

  for (const session of scheduled) {
    const li = document.createElement("li");
    li.className = "session-card";

    const title = document.createElement("p");
    title.className = "session-card__title";
    title.textContent = session.title;
    li.appendChild(title);

    const meta = document.createElement("p");
    meta.className = "session-card__meta";
    meta.textContent = formatSessionMeta(session);
    li.appendChild(meta);

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "btn";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", () => removeFromSchedule(session.sessionId));
    li.appendChild(removeBtn);

    list.appendChild(li);
  }
}

// ---------------------------------------------------------------------------
// Step 4: notes
// ---------------------------------------------------------------------------

function renderNoteSessionOptions() {
  const select = el("note-session-select");
  const scheduled = state.sessions.filter((s) => state.scheduleIds.has(s.sessionId));
  select.innerHTML = "";
  if (scheduled.length === 0) {
    select.innerHTML = '<option value="">Add a session to your schedule first</option>';
    return;
  }
  for (const session of scheduled) {
    const option = document.createElement("option");
    option.value = session.sessionId;
    option.textContent = session.title;
    select.appendChild(option);
  }
}

async function submitNote(event) {
  event.preventDefault();
  const sessionId = el("note-session-select").value;
  const text = el("note-text").value.trim();
  const recordingUrl = el("note-recording-url").value.trim();
  if (!sessionId || !text) return;

  try {
    await api("/api/notes", {
      method: "POST",
      body: { session_id: sessionId, text, recording_url: recordingUrl || null },
    });
    el("note-text").value = "";
    el("note-recording-url").value = "";
    await refreshNotes();
  } catch (err) {
    alert(`Failed to save note: ${err.message}`);
  }
}

async function refreshNotes() {
  state.notes = await api("/api/notes");
  renderNotes();
}

function renderNotes() {
  const list = el("notes-list");
  list.innerHTML = "";
  if (state.notes.length === 0) {
    list.innerHTML = '<li class="status">No notes captured yet.</li>';
    return;
  }
  const sessionsById = new Map(state.sessions.map((s) => [s.sessionId, s]));
  for (const note of state.notes) {
    const li = document.createElement("li");
    li.className = "note-card";

    const sessionLine = document.createElement("p");
    sessionLine.className = "note-card__session";
    const session = sessionsById.get(note.sessionId);
    sessionLine.textContent = session ? session.title : note.sessionId;
    li.appendChild(sessionLine);

    const textLine = document.createElement("p");
    textLine.className = "note-card__text";
    textLine.textContent = note.text;
    li.appendChild(textLine);

    if (note.recordingUrl) {
      const recLine = document.createElement("p");
      recLine.className = "note-card__recording";
      const link = document.createElement("a");
      link.href = note.recordingUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Recording (attendee-supplied)";
      recLine.appendChild(link);
      li.appendChild(recLine);
    }

    list.appendChild(li);
  }
}

// ---------------------------------------------------------------------------
// Step 5: reports
// ---------------------------------------------------------------------------

async function generateReport(reportType) {
  const attendeeName = el("attendee-name").value.trim() || "Attendee";
  const output = el("report-output");
  output.innerHTML = '<p class="status">Generating…</p>';
  try {
    const result = await api(`/api/reports/${reportType}`, {
      method: "POST",
      body: { attendee_name: attendeeName },
    });
    output.innerHTML = result.html;
  } catch (err) {
    output.innerHTML = `<p class="status status--error">Failed to generate report: ${err.message}</p>`;
  }
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

function init() {
  el("load-event-btn").addEventListener("click", selectEvent);
  el("session-filter").addEventListener("input", renderSessionList);
  el("note-form").addEventListener("submit", submitNote);
  el("prep-card-close").addEventListener("click", () => el("prep-card-dialog").close());

  for (const button of document.querySelectorAll("[data-report]")) {
    button.addEventListener("click", () => generateReport(button.dataset.report));
  }

  loadEvents();
}

init();
