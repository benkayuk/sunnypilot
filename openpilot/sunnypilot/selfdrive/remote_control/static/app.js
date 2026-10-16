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

const COMMAND_RATE_HZ = 30;             // POST /steer this often while armed
const COMMAND_INTERVAL_MS = Math.round(1000 / COMMAND_RATE_HZ);
const STATUS_POLL_MS = 500;             // GET /status this often
const MAX_SEND_FAILURES = 3;            // auto-disarm after this many back-to-back POST errors
const DEFAULT_MAX_ANGLE = 30;           // overridden by server /status

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
}

function onTouchEnd() {
  state.touchActive = false;
  state.touchAngle = 0;
  setAngleDisplay(0);
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

async function sendCommand() {
  if (!state.armed) return;
  const angle = state.touchActive ? state.touchAngle : 0;
  try {
    await postJSON("/steer", {angle});
    state.sendFailures = 0;
    if (state.lastSendOk !== true) {
      setConnection("ok", "Connected");
      state.lastSendOk = true;
    }
  } catch (e) {
    state.sendFailures += 1;
    state.lastSendOk = false;
    setConnection("warn", `Lost (${state.sendFailures}/${MAX_SEND_FAILURES})`);
    if (state.sendFailures >= MAX_SEND_FAILURES) {
      toast("Connection lost — disarming");
      // Fire-and-forget — if the server is actually gone, this will fail
      // too, but the server-side watchdog + carcontroller freshness check
      // are the real safety here. UI auto-disarms either way.
      try { await postJSON("/disarm", {}); } catch (_) { /* ignore */ }
      setArm(false);
    }
  }
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
