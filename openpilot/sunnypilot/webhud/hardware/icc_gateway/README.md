# ICC CAN gateway board (Fisker Ocean, IBUS1 / IBUS2 man-in-the-middle)

KiCad 10 project. Sits between the car harness and the ICC (head unit) main connector J1
(Molex stAK50h 160013-0641), passes every circuit straight through except the two CAN buses,
which go through a Teensy 4.1 gateway with a normally-closed relay bypass.

## Files

| File | What |
|---|---|
| `icc_gateway.kicad_pro/.kicad_sch` | root sheet: five sub-sheets |
| `connectors.kicad_sch` | J1 (car harness header) and J2 (ICC-side solder field), 58 pass-through nets, CAN taps |
| `power.kicad_sch` | fuse, reverse/TVS protection, LMR36510 5 V buck, wake logic on EN |
| `can.kicad_sch` | 2x TJA1043 (car side, INH wake) + 2x TJA1051T/3 (ICC side), ESD, decoupling |
| `bypass.kicad_sch` | 4x G6S-2 relays (bridge + switched 120 R terminators), ULN2003A driver |
| `mcu.kicad_sch` | Teensy 4.1, MCP2518FD (SPI, 4th CAN), KL15 sense, LEDs, RTC cell |
| `lib/icc_gateway.kicad_sym` | stAK50h connector symbol (2 units: bay A / bay B), typed Teensy 4.1 symbol |
| `lib/icc_gateway.pretty/Molex_stAK50h_160013-0641.kicad_mod` | header footprint built from Molex SD-160013-0001 |
| `lib/icc_gateway.pretty/ICC_wire_pads_2x29.kicad_mod` | J2: 58 solder holes for the ICC pigtail (1.3 mm signal, 2.0 mm power/speaker), grouped like the header |
| `lib/teensy.pretty/Teensy41.kicad_mod` | Teensy 4.1 footprint (XenGi community library) |

Schematic edits were made through the Konnect MCP tools (`tools/konnect_mcp.py` is a stdio client for
it). `tools/design.py` holds the full component and net table, `tools/footprint_stak50h.py` generates
the header footprint, `tools/place_plan.py` the board placement.

## Connector facts (from the Molex sales drawing)

- 2 bays x 29 circuits. Per bay: circuits 1-8 are the 1.20 mm blades (two rows of four on
  4.00 mm pitch, d1.30 holes), circuits 9-29 are 0.50 mm terminals (three rows of seven on
  2.00 mm pitch, d1.10 holes). Rows are 3.00 mm apart at 13.30 / 16.30 / 19.30 / 22.30 / 25.30
  from the locator-peg row; circuits 23-29 are the row nearest the pegs, 1-4 the farthest.
- Locator pegs 2x d3.75 on 29.85 mm centers, 8.85 mm behind the mating-face edge. Bay pitch
  19.60 mm. Body 40.39 mm wide.
- **Pin-1 handedness must be verified on a sample header before ordering boards.** Molex's
  "PCB layout for reference" picture puts circuit 1 bottom-left with the face at the top. The
  section view shows the top face rows landing farthest from the face, and the front view has
  pin 1 top-left, which together put pin 1 on the *right* of a component-side view. The
  footprint therefore mirrors Molex's picture (`MIRROR = True` in `footprint_stak50h.py`).
  Check with a continuity test from the face to the tails on one header; if pin 1 is on the
  left when the face points away from you, set `MIRROR = False` and regenerate.

## Pin assignment (Teensy 4.1)

| Function | Teensy pin |
|---|---|
| CAN1 (car IBUS1, TJA1043 U2) | 22 TX / 23 RX |
| CAN2 (car IBUS2, TJA1043 U3) | 1 TX / 0 RX |
| CAN3 (ICC IBUS1, TJA1051T/3 U4) | 31 TX / 30 RX |
| SPI to MCP2518FD (ICC IBUS2, U5) | 11 MOSI, 12 MISO, 13 SCK, 10 CS, 9 INT |
| Relays RLY1..RLY4 (K1 bridge IBUS1, K2 bridge IBUS2, K3 terms IBUS1, K4 terms IBUS2) | 2, 3, 4, 5 |
| U2 STBN / EN / ERRN | 6 / 7 / 8 |
| U3 STBN / EN / ERRN | 14 / 15 / 16 |
| KL15 sense (100k/22k divider) | 17 (A3) |
| LEDs active / car / ICC | 24 / 25 / 26 |

The Teensy plugs into two 1x24 female 2.54 mm socket strips (add them to the order; they are not
in the schematic BOM). Only the two outer pin rows are used; the inboard VBAT pad cannot reach a
socket, so there is no RTC backup cell.

Cut the Teensy's VUSB-to-VIN pad before the first external power-up.

## ICC side

J2 is a solder field, not a second header. Make one pigtail: a 160014-0014 (bay A, key 4) and a
160014-0011 (bay B, key 1) receptacle with crimped leads, or a salvaged ICC harness stub, and solder the
58 wires into J2 (square pad = circuit 1 of each bay, bay B on the left, bay A on the right, circuits
1-8 on the large holes). This avoids a second header and a second set of 0.5 mm crimps.

## Power and wake

VBATT (J1-A1) -> 0.5 A polyfuse -> SS36 -> SMBJ33A clamp -> `VIN_PROT` -> LMR36510 (5 V, up to
65 V in) -> Teensy VIN. The regulator EN is pulled down and driven through BAT54 diodes from the
two TJA1043 INH outputs and from KL15 (10k), so the board is unpowered while the car sleeps and
wakes on either bus or on ignition. KL15 also feeds both TJA1043 WAKE pins through 10k.

## Relay bypass

De-energized (board off or dead): K1/K2 bridge car<->ICC on both buses and K3/K4 leave the
on-board 120 R terminators disconnected, so the ICC sits on the stock buses. Energized: the
bridges open, the gateway's four transceivers own the four segments, and the terminators
(car-side and ICC-side, both buses) are switched in. Populate R20/R22 (car-side terminators)
only if the measurement at the ICC connector shows the car bus lost its terminator when the
ICC was cut.

## Status (2026-10-07)

- Schematic complete, ERC clean (0/0). `icc_gateway_schematic.pdf`, `icc_gateway_bom.csv`.
- PCB routed and **DRC clean (0 errors)**: 110 x 100 mm, 4 layers (F.Cu signal, In1.Cu GND plane, In2.Cu
  signal, B.Cu signal), solid GND pours top and bottom, netclasses Power 1.0 mm / Audio 0.8 / CAN 0.3 /
  Default 0.15, min clearance 0.15, min track 0.09 (Freerouting neck-downs at pads), vias 0.6/0.3.
  Fab as a JLCPCB 4-layer board. Gerbers + drills: `gerbers/`, `icc_gateway_gerbers.zip`.
  Renders: `routing/icc_gateway_final_top.png`, `routing/icc_gateway_final_bottom.png`.
- Assembly: `assembly/icc_gateway-cpl.csv` (JLCPCB pick-and-place columns, KiCad coordinates, all 66 placed
  footprints on Top, rotations as placed) and `assembly/icc_gateway-bom-jlc.csv` (JLC columns; the LCSC
  part number column is empty and must be filled before ordering SMT assembly). The raw KiCad position
  file is `assembly/icc_gateway-positions.csv`. `assembly/icc_gateway-bom-mouser.csv` is the ordering BOM with
  manufacturer and Mouser part numbers (stock checked 2026-10-07); the MCP2518FD SOIC is backordered at
  Mouser, the MCP2517FD-H/SL is the in-stock drop-in.
- Remaining DRC warnings are cosmetic (silk overlaps, tiny Teensy silk text, the J1 silk box clipped
  at the board edge where the connector face overhangs, four mounting holes not in the schematic).
- Routing was done with Freerouting 2.5.0 (`tools/route_pipeline_r2.sh`: KiCad python DSN export, Freerouting,
  SES import) plus hand fixes in `tools/fixup*.py` and `tools/gnd_fixup.py`.

## Before ordering

1. Verify stAK50h pin-1 handedness on a sample header (see "Connector facts"); flip `MIRROR` and regenerate
   `Molex_stAK50h_160013-0641` + re-run the schematic sync if it is wrong.
2. Check J1's mating-face overhang against the enclosure: the face sits 8.85 mm in front of the pegs and
   the board edge is at the face plane.
3. Measure the car-side bus termination before populating R20/R22.
