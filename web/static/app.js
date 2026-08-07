const $ = (id) => document.getElementById(id);
const SESSION_KEY = "wyldstallyns_session";
// The traveler's current in-flight trip, so the lock + result survive a reload.
const TRIP_KEY = "wyldstallyns_trip";

// Escape anything interpolated into innerHTML. Booking fields (destination,
// mission, etc.) are attacker-controllable and are rendered in Rufus's admin
// queue, so unescaped output would be a stored-XSS path.
const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Customer dropdown options (Bill & Ted's greatest hits).
const DESTINATIONS = [
  "Ancient Greece, 410 B.C. — So-crates Johnson",
  "Austria, 1805 — Napoleon Bonaparte",
  "New Mexico, 1879 — Billy the Kid",
  "France, 1429 — Joan of Arc",
  "Washington D.C., 1863 — Abraham Lincoln",
  "Vienna, 1810 — Ludwig van Beethoven",
  "Mongolia, 1209 — Genghis Khan",
  "Vienna, 1901 — Sigmund Freud",
  "San Dimas, 1988 — home base",
];
const MISSIONS = [
  "Ace our history report",
  "Assemble a most excellent band",
  "Save the future",
  "Be excellent to each other",
];

// ---- session helpers ------------------------------------------------------

function session() {
  const raw = sessionStorage.getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    // Corrupt/partial storage would otherwise throw on every render; drop it.
    sessionStorage.removeItem(SESSION_KEY);
    return null;
  }
}
function authHeaders() {
  const s = session();
  // Only send a token when we actually have one. "No license" sends nothing, so
  // the client interceptor rejects the booking before it starts.
  return s && s.token ? { Authorization: "Bearer " + s.token } : {};
}

// ---- login / logout -------------------------------------------------------

async function loadIdentities() {
  const sel = $("identity");
  try {
    const res = await fetch("/api/identities");
    if (!res.ok) throw new Error("HTTP " + res.status);
    const { identities } = await res.json();
    sel.innerHTML = "";
    for (const i of identities) {
      const suffix = i.role === "admin" ? " — administrator" : "";
      sel.add(new Option(i.label + suffix, i.value));
    }
  } catch {
    // Transient failure (e.g. the web pod is still starting): don't wipe any
    // options we already have, and retry shortly so the dropdown self-heals
    // instead of staying blank until a manual reload.
    if (!sel.options.length) setTimeout(loadIdentities, 1500);
  }
}

async function doLogin() {
  const identity = $("identity").value;
  const res = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identity }),
  });
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(await res.json()));
  render();
}

function logout() {
  sessionStorage.removeItem(SESSION_KEY);
  // Clear the previous trip so it doesn't linger when someone logs back in.
  sessionStorage.removeItem(TRIP_KEY);
  clearInterval(trackTimer);
  const box = $("result");
  if (box) {
    box.classList.add("hidden");
    box.innerHTML = "";
  }
  setBookEnabled(true);
  render();
}

// ---- view rendering -------------------------------------------------------

function fillSelect(id, values) {
  const sel = $(id);
  if (sel.options.length) return;
  for (const v of values) sel.add(new Option(v, v));
}

function render() {
  const s = session();
  if (!s) {
    $("login").classList.remove("hidden");
    $("app").classList.add("hidden");
    loadIdentities();
    return;
  }
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");

  const isAdmin = s.role === "admin";
  const jwtLine = s.token
    ? `<div class="jwt"><span class="jwt-label">JWT</span><code id="jwt-val">${esc(s.token)}</code>` +
      `<button id="copy-jwt" class="ghost">Copy</button></div>` +
      `<p class="hint">This exact token is stamped on the workflow header — find it in the Temporal Web UI and the backend logs.</p>`
    : `<div class="jwt"><span class="jwt-label">JWT</span><em>no license</em></div>`;
  $("whoami").innerHTML =
    `<div class="who">Logged in as <strong>${esc(s.name)}</strong> ` +
    `<span class="role">${esc(s.role)}</span>` +
    (s.group && s.group !== "—" ? ` <span class="plan">${esc(s.group)}</span>` : "") +
    `<button id="logout" class="ghost">Log out</button></div>` +
    jwtLine;
  $("logout").onclick = logout;
  if (s.token) {
    $("copy-jwt").onclick = () => navigator.clipboard?.writeText(s.token);
  }

  $("admin").classList.toggle("hidden", !isAdmin);
  $("customer").classList.toggle("hidden", isAdmin);

  if (isAdmin) {
    refreshQueue();
  } else {
    fillSelect("destination", DESTINATIONS);
    fillSelect("mission", MISSIONS);
    resumeTrip(); // restore an in-flight trip's lock + progress after a reload
  }
}

// ---- booking (customer) ---------------------------------------------------

const BADGE = {
  completed: ["b-ok", "EXCELLENT!"],
  failed: ["b-bad", "BOGUS!"],
  rejected: ["b-bad", "BOGUS — DENIED"],
  awaiting_review: ["b-warn", "WHOA — FLAGGED FOR RUFUS"],
  starting: ["b-warn", "FIRING UP THE BOOTH…"],
  scanning: ["b-warn", "SCANNING FOR PARADOX…"],
  jumping: ["b-warn", "JUMPING THROUGH TIME…"],
};
// A trip is done only in these states; anything else means keep polling.
const TERMINAL = new Set(["completed", "failed", "rejected"]);

let trackTimer = null;

// One trip per traveler: lock the booth while a trip is in flight (the server
// enforces this too). Re-enabled when the trip reaches a terminal state.
function setBookEnabled(on) {
  const b = $("book");
  if (!b) return;
  b.disabled = !on;
  b.textContent = on ? "Fire up the booth" : "Trip in progress…";
}

// Render the result box for a trip snapshot. Handles both the /api/book reply
// (which may carry state under `detail`) and /api/trip polls.
function renderResultBox(data) {
  const box = $("result");
  box.classList.remove("hidden");
  const status = data.status || "unknown";
  const [cls, text] = BADGE[status] || ["b-warn", status.toUpperCase()];
  const awaiting = status === "awaiting_review";
  const msg =
    data.message ||
    (data.detail && data.detail.reason) ||
    (awaiting ? "Strange things are afoot at the Circuits of Time. Rufus has to review this one." : "");
  let note = "";
  if (awaiting)
    note = `<div class="waiting">⏳ Waiting for Rufus's decision…</div>`;
  else if (!TERMINAL.has(status))
    note = `<div class="waiting">⏳ Traveling the Circuits of Time…</div>`;
  box.innerHTML =
    `<span class="badge ${cls}">${text}</span><br/>${esc(msg)}` +
    note +
    (data.workflow_id ? `<div class="mono">booth trip: ${esc(data.workflow_id)}</div>` : "");
}

// The client interceptor's get_token callback refreshes an expiring license on the
// way through and the server hands the new one back here. Store it, or we'd keep
// sending the stale token and refresh on every booking.
function adoptRefreshedToken(data) {
  if (!data || !data.token) return;
  const s = session();
  if (!s) return;
  sessionStorage.setItem(SESSION_KEY, JSON.stringify({ ...s, token: data.token }));
  render();
}

function showResult(data) {
  adoptRefreshedToken(data);
  renderResultBox(data);
  const wf = data.workflow_id;
  const status = data.status || "";
  if (wf && !TERMINAL.has(status)) {
    // In flight (incl. awaiting_review): lock the booth and track it,
    // remembering it so a reload restores the lock + progress.
    sessionStorage.setItem(TRIP_KEY, wf);
    setBookEnabled(false);
    trackTrip(wf);
  } else if (wf && TERMINAL.has(status)) {
    // This trip finished — free the booth.
    if (sessionStorage.getItem(TRIP_KEY) === wf) sessionStorage.removeItem(TRIP_KEY);
    setBookEnabled(true);
  } else {
    // No workflow (license/entitlement reject, or the "already in flight" guard):
    // stay locked if a trip is still active, otherwise free the booth.
    setBookEnabled(!sessionStorage.getItem(TRIP_KEY));
  }
}

// Restore an in-flight trip's lock + result after a page reload / re-render.
async function resumeTrip() {
  const wf = sessionStorage.getItem(TRIP_KEY);
  if (!wf) return;
  try {
    const res = await fetch(`/api/trip/${wf}`, { headers: authHeaders() });
    if (!res.ok) {
      sessionStorage.removeItem(TRIP_KEY);
      return;
    }
    showResult(await res.json());
  } catch {
    /* leave the key; a later render will retry */
  }
}

// Poll a trip until it reaches a terminal state, re-rendering the box each time
// so status changes show live.
function trackTrip(workflow_id) {
  clearInterval(trackTimer);
  trackTimer = setInterval(async () => {
    if (!session()) return clearInterval(trackTimer);
    let data;
    try {
      const res = await fetch(`/api/trip/${workflow_id}`, { headers: authHeaders() });
      if (!res.ok) return;
      data = await res.json();
    } catch {
      return;
    }
    renderResultBox(data);
    if (TERMINAL.has(data.status)) {
      clearInterval(trackTimer);
      if (sessionStorage.getItem(TRIP_KEY) === workflow_id) sessionStorage.removeItem(TRIP_KEY);
      setBookEnabled(true);
    }
  }, 2500);
}

async function book() {
  const btn = $("book");
  btn.disabled = true;
  btn.textContent = "Firing up the booth…";
  try {
    const res = await fetch("/api/book", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        destination: $("destination").value,
        mission: $("mission").value,
        force_review: $("force_review").checked,
      }),
    });
    showResult(await res.json()); // showResult owns the button state from here
  } catch (e) {
    $("result").classList.remove("hidden");
    $("result").textContent = "Bogus! " + e;
    setBookEnabled(true);
  }
}

// ---- review queue (Rufus) -------------------------------------------------

async function refreshQueue() {
  if (!session() || session().role !== "admin") return;
  const res = await fetch("/api/trips", { headers: authHeaders() });
  if (!res.ok) return;
  const { trips } = await res.json();
  const q = $("queue");
  q.innerHTML = "";
  if (!trips.length) {
    q.innerHTML = '<p class="empty">No trips on the Circuits of Time right now. Party on.</p>';
    return;
  }
  for (const t of trips) {
    const review = t.status === "awaiting_review"; // flagged, awaiting a decision
    const el = document.createElement("div");
    el.className = "trip";
    el.innerHTML =
      `<div class="dest">${esc(t.destination)}` +
      ` <span class="role">${esc(t.status)}</span></div>` +
      `<div class="meta">dude: ${esc(t.traveler_name)} (${esc(t.traveler_id)})` +
      (t.mission ? ` · mission: ${esc(t.mission)}` : "") +
      `</div>` +
      (review ? `<div class="reason">⚠ ${esc(t.reason)}</div>` : "") +
      `<div class="actions"></div>` +
      `<div class="mono">booth trip: ${esc(t.workflow_id)}</div>`;
    const actions = el.querySelector(".actions");
    // Approve/reject for a flagged trip awaiting a decision.
    if (review) {
      actions.append(
        Object.assign(document.createElement("button"), {
          className: "approve",
          textContent: "Excellent (approve)",
          onclick: () => decide(t.workflow_id, "approved"),
        }),
        Object.assign(document.createElement("button"), {
          className: "reject",
          textContent: "Bogus (reject)",
          onclick: () => decide(t.workflow_id, "rejected"),
        }),
      );
    }
    q.append(el);
  }
}

async function decide(workflow_id, decision) {
  await fetch("/api/review", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ workflow_id, decision }),
  });
  setTimeout(refreshQueue, 400);
}

// ---- init -----------------------------------------------------------------

$("do-login").addEventListener("click", doLogin);
$("book").addEventListener("click", book);
$("refresh").addEventListener("click", refreshQueue);

// Rufus's queue refreshes often enough to catch a short-lived trip in time to
// review it, but only while the tab is visible — each poll costs a Query Action
// per running trip, so we don't burn them while nobody's looking. Use the
// Refresh button for an immediate check.
const QUEUE_POLL_MS = 4000;
setInterval(() => {
  if (!document.hidden) refreshQueue();
}, QUEUE_POLL_MS);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshQueue();
});

render(); // render() loads the identity dropdown when it shows the login view
