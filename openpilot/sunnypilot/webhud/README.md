# sunnypilot web HUD bridge

The comma's half of the Fisker Ocean HUD. The HUD itself is
[Oceanfront View](https://github.com/moistpope/oceanfront-view): a web page with a 3D model of the car,
the lanes, cars, signs and lights its ADAS sees, the road from the map, the car's own state and
controls, music and navigation. It runs on the car's own screen in its Android app, or in a browser
from its `serve.py`, and decodes the buses and runs its world model itself, in a web worker. This
process feeds it.

**What the bridge does.** It reads the ADAS bus, the radar's private bus (panda bus 1) and openpilot's
own services and streams them as they are, in ticks at 20 Hz over a WebSocket (`/ws`): raw CAN frames
allowlisted by message (the set in `openpilot/third_party/webhud/dbc/fisker_ocean_adas_world.dbc`, of
which Oceanfront View keeps the same copy, and the radar's `opendbc/dbc/fisker_ocean_mrr.dbc`), and the
services in compact form (`extract.py`). A viewer that just connected first gets a snapshot of the latest
frame of every message; one that falls behind gets its missed ticks merged, never dropped. The REST API
carries status, replay of recorded routes (rlog/qlog, uploads too), the editable CAN overrides
(`FiskerCanOverrides`, applied in place by `selfdrive/car/can_overrides.py`) and a few params; `/map/...`
fetches the OSM road tiles the page's map matcher reads (`maptiles.py`, mapd's own files) and point
features from Overpass. `sunnypilot.local` is published over mDNS. The process is niced and reads nothing
while no viewer is connected.

**The camera view.** A second WebSocket, `/video` (`video.py`), carries the road camera for the page's
camera view: the livestream encoder's H.264 (1280x720, a keyframe every 5 frames, the same stream comma's
livestream sends) passed through untouched, and what the comma's own driving screen draws over it -- the
model's path, lane lines, road edges and leads, with the camera projection from the calibration, and the rest of
the comma 4 screen's state (`hud`: the status that colours it, set speed, steering angle and torque, the alert,
driver monitoring, blind spots, the model's confidence) about 20 times a second, so the page can mirror it. The page
decodes the video (WebCodecs) and draws the overlay itself, matched to each frame by frame id. While a
viewer is connected `WebHudVideo` is set, and the manager runs camerad and `stream_encoderd` for it, onroad
too (comma's own livestream stops at ignition); 10 s after the last viewer leaves it is cleared again.

**It serves no page.** The Android app carries the page in its APK and relays `/api` and `/ws` here; on
a PC, `python3 serve.py --bridge sunnypilot.local` in the Oceanfront View checkout does the same. `/`
answers with a short text saying so. Set `WEBHUD_PAGE_DIR=<oceanfront-view checkout>` and the bridge
serves the page as well (`/`, `/vendor/`, `/models/`, `/dbc/` from that checkout's `static/`,
`third_party/` and `dbc/`), for a plain browser against `http://sunnypilot.local:8088`.

**Toggle:** *Settings → Developer → Web HUD* (`EnableWebHud`, on by default); `webhud` in
`process_config.py`. Port 8088, and 80 when the process may bind it.

## Pieces

| File | Role |
|------|------|
| `server.py` | Process entry point (`webhud` in process_config). stdlib `http.server` + WebSocket, 20 Hz tick stream (raw frames + service extracts), REST API, the DBCs as static files. |
| `state.py`, `extract.py` | `StreamBuilder`: the frames and service extracts gathered since the last tick, and the latest of each for a viewer that just connected; the extractors turn openpilot/sunnypilot services into compact JSON. |
| `sources.py` | Live (cereal `can` + services) and rlog/qlog replay (zst/bz2, multi-segment, seek, speed). |
| `demo.py` | Synthetic drive that encodes real ADASBUS frames: `server.py --demo` or *Playback → Play demo drive* in the HUD. |
| `dbc.py` | Small DBC reader/decoder (the demo encodes with it; the overrides API shows the ICC's live values through it). Oceanfront View's `static/js/world/dbc.js` is its twin in the page. |
| `mdns.py` | Publishes `sunnypilot.local` as an alias + `_http._tcp` service through avahi's D-Bus API (jeepney); falls back to a built-in A-record responder. Doesn't change the device hostname. |
| `maptiles.py` | OSM road tiles (mapd's cells, downloaded on first use), Overpass point features, and the prefetch of everything within a radius of the car. |
| `video.py` | The camera view's `/video` socket: turns the livestream encoder on while watched, passes its frames through and sends the overlay and the camera projection. |
| `websocket.py` | The WebSocket framing. |
| `paths.py` | Where the DBCs are, and the optional page directory. |
| `../selfdrive/car/can_overrides.py` | Validates/applies `FiskerCanOverrides`; card polls it at 10 Hz and updates the dicts carcontroller reads, in place. |
| `tools/fisker_handoff_audit.py` | Audits a recorded drive's relay handoffs with opendbc's `relay_audit`. |
| `../../third_party/webhud/dbc/` | The ADASBUS subset the bridge streams by, generated in Oceanfront View (`tools/gen_world_dbc.py` there) from the FM29 matrix. |

## API

`GET /api/status`, `GET /api/routes`, `POST /api/replay {action: load|play|pause|toggle|seek|step|speed|live|demo, ...}`,
`GET /map/tile/<lat>/<lon>/<name>` (an OSM road tile, fetched into mapd's folder on first use),
`GET /map/features/<klat>/<klon>`, `POST /map/prefetch {lat, lon, radius_km}`, `GET /map/status`,
`PUT /api/upload?name=<file>` (raw rlog/qlog body), `GET|PUT /api/params` (personality, experimental
mode, units), `GET|PUT|DELETE /api/overrides`, `GET /api/ssh` (SSH on or off, the keys let in, by
fingerprint), `POST|DELETE /api/ssh/authorize {publicKey}` (add or remove one OpenSSH public key line in
`GithubSshKeys`, beside the keys already there; adding also turns SSH on: the Oceanfront View app puts its own
key on the comma this way, then manages it over SSH as `comma`). Static: `/dbc/` (the ADASBUS subset and the radar DBC,
which the page decodes with), and the page with `WEBHUD_PAGE_DIR` set. WebSocket `/ws`: the server sends
`{type: hello}` then `{type: tick, data: {now, reset?, brand, can: [[t, [[addr, bus, hex], ...]], ...],
op: [[service, t, extract], ...], mode, replay, server}}` at 20 Hz (the first tick for a new viewer is a
snapshot of the latest frame of every message, with `reset`); the client sends `{type: replay, ...}`.
WebSocket `/video?camera=road|wide`: binary frames (a 16-byte header `<BBHIQ`: kind 1, flags bit 0 =
keyframe, camera 0 road / 1 wide, frameId, timestampEof ns; then the Annex B access unit) and text
`{type: hello | calib | model | hud | error}` (`video.py` has the fields); the client sends `{type: camera, camera}`.

Writes are accepted from private addresses only, never cross-origin, and CAN override changes, SSH keys and
replay are refused while the car is moving (replay also stops itself if the car starts moving).

## Development

```
python -m openpilot.sunnypilot.webhud.server --demo            # synthetic drive
python -m openpilot.sunnypilot.webhud.server --replay <rlog.zst | segment dir | route dir>
python -m openpilot.sunnypilot.webhud.server --replay <rlog.zst> --map-root <dir of OSM cells>   # the map from somewhere other than mapd's folder
WEBHUD_PAGE_DIR=~/oceanfront-view python -m openpilot.sunnypilot.webhud.server --demo   # and serve the page from that checkout
pytest openpilot/sunnypilot/webhud/tests                        # the bridge
```

On a PC without the native params library, settings are kept in `~/.comma/webhud_dev_params.json`.
The page's own tests and tools (`node --test`, the tick recorder and replayer) are in Oceanfront View.
