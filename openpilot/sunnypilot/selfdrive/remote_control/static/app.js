// Fisker Remote Control UI
//
// Phone-side watchdog:
//   * While armed, we POST /steer at COMMAND_RATE_HZ.
//   * If three consecutive sends fail, we assume the server (or wifi) is gone
//     and auto-disarm on the UI so the user sees it immediately — the server
//     plus the carcontroller's own freshness check are the authoritative
//     watchdog on the vehicle side.
//   * Status polling at 2 Hz keeps the connection pill honest when idle.
//
// Steering input model:
//   * The whole steer-track is a touch surface. x-position of the touch
//     relative to the track center = commanded angle, scaled linearly to the
//     full ±maxAngleDeg range.
//   * On touchend/touchcancel, the UI snaps the angle back to 0 — the car
//     goes straight if the user lifts their finger (spring-return).
//   * While not touching, we still send angle=0 at the command rate so the
//     carcontroller watchdog stays fresh (otherwise the "ok we're alive but
//     the user isn't touching" case would trigger a watchdog fallback).

// Heartbeat rate. 30 Hz is plenty — the carcontroller's freshness window is
// 300 ms, so this gives ~9× safety margin, and the panda-enforced angle
// slew rate (250°/s at 0 m/s) means a one-tick param-write delay is well
// under 1% of the time it takes the EPS to physically move the wheel.
// Previously tried 100 Hz but it strained the stdlib ThreadingHTTPServer
// (thread-per-request + per-POST LMDB write) and manifested as
// "connection lost" flapping over wifi.
const COMMAND_RATE_HZ = 30;             // POST /steer this often while armed (heartbeat)
const COMMAND_INTERVAL_MS = Math.round(1000 / COMMAND_RATE_HZ);
const STATUS_POLL_MS = 500;             // GET /status this often
const MAX_SEND_FAILURES = 15;           // auto-disarm after this many back-to-back POST errors (~500 ms of flakiness)
const DEFAULT_MAX_ANGLE = 250;          // overridden by server /status

const el = (id) => document.getElementById(id);

const state = {
  armed: false,
  maxAngleDeg: DEFAULT_MAX_ANGLE,
  touchAngle: 0,          // deg, driven by current touch position (0 if not touching)
  touchActive: false,
  lastSendOk: null,       // true/false/null
  sendFailures: 0,
  statusTimer: null,
  commandTimer: null,
  // In-flight guard: never allow more than one /steer POST in flight at
  // once. If a POST is still waiting on a server response, newer ticks
  // (heartbeat or touchmove) drop their send — the next completed POST
  // will pick up the latest touchAngle immediately after. Prevents the
  // request-pileup / "connection lost" flapping that was happening when
  // touchmove and heartbeat raced.
  sendInFlight: false,
};

// ---------------------------------------------------------------- net helpers

async function postJSON(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body || {}),
    cache: "no-store",
    keepalive: true,
  });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

async function getJSON(path) {
  const r = await fetch(path, {cache: "no-store"});
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

// ---------------------------------------------------------------- UI updaters

function setConnection(status, label) {
  const pill = el("connectionPill");
  pill.classList.remove("ok", "warn", "err");
  if (status) pill.classList.add(status);
  el("connectionLabel").textContent = label;
}

function setArm(armed) {
  state.armed = armed;
  const pill = el("armPill");
  pill.classList.remove("ok", "warn", "err");
  if (armed) {
    pill.classList.add("warn");
    el("armLabel").textContent = "App Controlling";
    el("armBtn").classList.add("hidden");
    el("disarmBtn").classList.remove("hidden");
    el("steerTrack").classList.remove("disabled");
  } else {
    el("armLabel").textContent = "Sunnypilot";
    el("armBtn").classList.remove("hidden");
    el("disarmBtn").classList.add("hidden");
    el("steerTrack").classList.add("disabled");
  }
}

function setAngleDisplay(deg) {
  const v = el("angleValue");
  const rounded = Math.round(deg);
  v.textContent = `${rounded >= 0 ? "+" : ""}${rounded}°`;
  v.classList.remove("left", "right");
  if (rounded < 0) v.classList.add("left");
  else if (rounded > 0) v.classList.add("right");

  // Thumb position mirrors angle. 0 → center, ±max → edges.
  const thumb = el("steerThumb");
  const track = el("steerTrack");
  const trackWidth = track.clientWidth;
  const halfRange = state.maxAngleDeg || DEFAULT_MAX_ANGLE;
  const frac = Math.max(-1, Math.min(1, deg / halfRange));
  // Thumb width is 70px, center = 50% of track
  const px = frac * (trackWidth / 2 - 35);
  thumb.style.transform = `translateX(${px}px)`;
}

function toast(msg, ms = 1800) {
  const t = el("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => t.classList.remove("show"), ms);
}

// ---------------------------------------------------------------- status loop

async function pollStatus() {
  try {
    const s = await getJSON("/status");
    state.maxAngleDeg = s.maxAngleDeg || DEFAULT_MAX_ANGLE;
    setConnection("ok", "Connected");
    // Reflect server-side armed state in case something else toggled it
    // (e.g. a watchdog on the carcontroller disabled remote control).
    if (s.armed !== state.armed) setArm(!!s.armed);
  } catch (e) {
    setConnection("err", "Disconnected");
    if (state.armed) {
      setArm(false);  // can't talk to server → UI must reflect disarmed
    }
  }
}

// ---------------------------------------------------------------- steer touch

function onTouchMove(ev) {
  if (!state.armed) return;
  const track = el("steerTrack");
  const rect = track.getBoundingClientRect();
  // Prefer the first touch; mouse falls through to clientX.
  const t = ev.touches ? ev.touches[0] : ev;
  const x = t.clientX - rect.left;
  const half = rect.width / 2;
  const frac = Math.max(-1, Math.min(1, (x - half) / half));
  const halfRange = state.maxAngleDeg || DEFAULT_MAX_ANGLE;
  state.touchAngle = frac * halfRange;
  state.touchActive = true;
  setAngleDisplay(state.touchAngle);
  // No POST from here — the 30 Hz heartbeat will pick up state.touchAngle
  // within ~33 ms, which is well below the panda-enforced slew rate (the
  // physical limit on how fast the EPS can move the wheel anyway). Firing
  // on every touchmove event used to send 60-120 Hz on top of the heartbeat
  // and overwhelmed the stdlib HTTP server, surfacing as "connection lost"
  // flapping.
}

function onTouchEnd() {
  state.touchActive = false;
  state.touchAngle = 0;
  setAngleDisplay(0);
  // Make the return-to-zero visible on the vehicle immediately rather than
  // waiting up to one heartbeat interval.
  sendNow();
}

function wireSteerTrack() {
  const track = el("steerTrack");
  track.addEventListener("touchstart", onTouchMove, {passive: true});
  track.addEventListener("touchmove",  onTouchMove, {passive: true});
  track.addEventListener("touchend",   onTouchEnd,  {passive: true});
  track.addEventListener("touchcancel", onTouchEnd, {passive: true});
  // Desktop debug: hold left mouse and drag.
  let mouseDown = false;
  track.addEventListener("mousedown", (e) => { mouseDown = true; onTouchMove(e); });
  window.addEventListener("mousemove", (e) => { if (mouseDown) onTouchMove(e); });
  window.addEventListener("mouseup",   () => { if (mouseDown) { mouseDown = false; onTouchEnd(); } });
}

// ---------------------------------------------------------------- command loop

// Fire a /steer POST with the current state, non-blocking. Called from the
// heartbeat interval AND from touchEnd (release-to-zero). Does NOT fire
// from touchmove — the 33 ms heartbeat picks up the latest touchAngle
// anyway, and firing on every touchmove event (60-120 Hz) was overwhelming
// the server. Guards against multiple in-flight POSTs so backpressure can't
// cause pileup over a flaky wifi link.
function sendNow() {
  if (!state.armed) return;
  if (state.sendInFlight) return;  // drop; next tick will carry a fresher value
  state.sendInFlight = true;
  const angle = state.touchActive ? state.touchAngle : 0;
  postJSON("/steer", {angle}).then(() => {
    state.sendInFlight = false;
    state.sendFailures = 0;
    if (state.lastSendOk !== true) {
      setConnection("ok", "Connected");
      state.lastSendOk = true;
    }
  }).catch(() => {
    state.sendInFlight = false;
    state.sendFailures += 1;
    state.lastSendOk = false;
    setConnection("warn", `Lost (${state.sendFailures}/${MAX_SEND_FAILURES})`);
    if (state.sendFailures >= MAX_SEND_FAILURES) {
      toast("Connection lost — disarming");
      try { postJSON("/disarm", {}); } catch (_) { /* ignore */ }
      setArm(false);
    }
  });
}

// Heartbeat tick: keeps the carcontroller's freshness watchdog fresh
// even when the finger isn't moving. Just delegates to sendNow().
function sendCommand() {
  sendNow();
}

// ---------------------------------------------------------------- buttons

async function onArm() {
  try {
    await postJSON("/arm", {});
    setArm(true);
    toast("App now controlling");
  } catch (e) {
    toast("Failed to arm — check connection");
  }
}

async function onDisarm() {
  try {
    await postJSON("/disarm", {});
  } catch (e) { /* ignore — manager-side will reset anyway */ }
  setArm(false);
  toast("Handed back to sunnypilot");
}

// ---------------------------------------------------------------- boot

function boot() {
  wireSteerTrack();
  el("armBtn").addEventListener("click", onArm);
  el("disarmBtn").addEventListener("click", onDisarm);
  setArm(false);
  setAngleDisplay(0);

  pollStatus();
  state.statusTimer = setInterval(pollStatus, STATUS_POLL_MS);
  state.commandTimer = setInterval(sendCommand, COMMAND_INTERVAL_MS);

  // Prevent accidental double-tap zoom and pull-to-refresh.
  document.addEventListener("gesturestart", (e) => e.preventDefault());
  document.body.addEventListener("touchmove", (e) => {
    // Allow touch inside the steer track; block pull-to-refresh elsewhere.
    if (!e.target.closest(".steer-track")) e.preventDefault();
  }, {passive: false});
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
