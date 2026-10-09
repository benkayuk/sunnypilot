"""Design table for the ICC gateway schematic: components per sheet and pin-level connections.

Connection kinds: 'g' global label, 'l' local label, 'p' power symbol (power:<net>), 'nc' no-connect.
"""
P = "/Users/evanelgin/sunnypilot-1/openpilot/sunnypilot/webhud/hardware/icc_gateway"
SHEET = {k: f"{P}/{k}.kicad_sch" for k in ("connectors", "power", "can", "bypass", "mcu")}

R = "Resistor_SMD:R_0805_2012Metric"
C = "Capacitor_SMD:C_0805_2012Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C1210 = "Capacitor_SMD:C_1210_3225Metric"
SOD123 = "Diode_SMD:D_SOD-123"
SOT23 = "Package_TO_SOT_SMD:SOT-23-3"
SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
SOIC14 = "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"
SOIC16 = "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
LED = "LED_SMD:LED_0805_2012Metric"

# (sheet, ref, lib_id, value, footprint, x, y, rotation)
COMPONENTS = [
    # ---------------- power ----------------
    ("power", "F1", "Device:Polyfuse", "0.5A 60V", "Fuse:Fuse_1812_4532Metric", 40, 40, 0),
    ("power", "D1", "Device:D_Schottky", "SS36", "Diode_SMD:D_SMA", 70, 40, 0),
    ("power", "D2", "Device:D_TVS", "SMBJ33A", "Diode_SMD:D_SMB", 95, 60, 90),
    ("power", "C1", "Device:C", "2.2uF 100V", C1210, 110, 60, 0),
    ("power", "C2", "Device:C", "2.2uF 100V", C1210, 125, 60, 0),
    ("power", "C3", "Device:C", "100nF 100V", C, 140, 60, 0),
    ("power", "U1", "Regulator_Switching:LMR36510ADDA", "LMR36510ADDAR", "Package_SO:Texas_HTSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.4x3.1mm_ThermalVias", 180, 60, 0),
    ("power", "C4", "Device:C", "100nF 16V (BOOT)", C0603, 215, 40, 0),
    ("power", "C5", "Device:C", "1uF 16V (VCC)", C0603, 165, 95, 0),
    ("power", "L1", "Device:L", "15uH 2A", "Inductor_SMD:L_Bourns_SRN6045TA", 230, 60, 0),
    ("power", "C6", "Device:C", "22uF 10V", C, 250, 80, 0),
    ("power", "C7", "Device:C", "22uF 10V", C, 265, 80, 0),
    ("power", "R1", "Device:R", "100k (FB top)", R, 250, 110, 0),
    ("power", "R2", "Device:R", "24.9k (FB bottom)", R, 250, 130, 0),
    ("power", "R3", "Device:R", "100k (EN pull-down)", R, 60, 120, 0),
    ("power", "R4", "Device:R", "10k (KL15 -> EN)", R, 40, 95, 0),
    ("power", "D3", "Device:D_Schottky", "BAT54 (INH1->EN)", SOD123, 60, 150, 0),
    ("power", "D4", "Device:D_Schottky", "BAT54 (INH2->EN)", SOD123, 60, 165, 0),
    ("power", "D5", "Device:D_Schottky", "BAT54 (KL15->EN)", SOD123, 60, 180, 0),
    # ---------------- can ----------------
    ("can", "U2", "Interface_CAN_LIN:TJA1043T", "TJA1043T/1 (car IBUS1)", SOIC14, 60, 60, 0),
    ("can", "U3", "Interface_CAN_LIN:TJA1043T", "TJA1043T/1 (car IBUS2)", SOIC14, 60, 160, 0),
    ("can", "U4", "Interface_CAN_LIN:TJA1051T-3", "TJA1051T/3 (ICC IBUS1)", SOIC8, 230, 60, 0),
    ("can", "U5", "Interface_CAN_LIN:TJA1051T-3", "TJA1051T/3 (ICC IBUS2)", SOIC8, 230, 160, 0),
    ("can", "C10", "Device:C", "100nF (U2 VCC)", C, 110, 30, 0),
    ("can", "C11", "Device:C", "100nF (U2 VIO)", C, 125, 30, 0),
    ("can", "C12", "Device:C", "100nF (U2 VBAT)", C, 140, 30, 0),
    ("can", "C13", "Device:C", "100nF (U3 VCC)", C, 110, 130, 0),
    ("can", "C14", "Device:C", "100nF (U3 VIO)", C, 125, 130, 0),
    ("can", "C15", "Device:C", "100nF (U3 VBAT)", C, 140, 130, 0),
    ("can", "C16", "Device:C", "100nF (U4 VCC)", C, 280, 30, 0),
    ("can", "C17", "Device:C", "100nF (U4 VIO)", C, 295, 30, 0),
    ("can", "C18", "Device:C", "100nF (U5 VCC)", C, 280, 130, 0),
    ("can", "C19", "Device:C", "100nF (U5 VIO)", C, 295, 130, 0),
    ("can", "R10", "Device:R", "10k (KL15 -> U2 WAKE)", R, 20, 95, 0),
    ("can", "R11", "Device:R", "10k (KL15 -> U3 WAKE)", R, 20, 195, 0),
    ("can", "D10", "Power_Protection:NUP2105L", "NUP2105L (car IBUS1 ESD)", SOT23, 160, 80, 0),
    ("can", "D11", "Power_Protection:NUP2105L", "NUP2105L (car IBUS2 ESD)", SOT23, 160, 180, 0),
    ("can", "D12", "Power_Protection:NUP2105L", "NUP2105L (ICC IBUS1 ESD)", SOT23, 330, 80, 0),
    ("can", "D13", "Power_Protection:NUP2105L", "NUP2105L (ICC IBUS2 ESD)", SOT23, 330, 180, 0),
    # ---------------- bypass ----------------
    ("bypass", "K1", "Relay:G6S-2", "G6S-2 DC5 (bridge IBUS1)", "Relay_THT:Relay_DPDT_Omron_G6S-2", 60, 50, 0),
    ("bypass", "K2", "Relay:G6S-2", "G6S-2 DC5 (bridge IBUS2)", "Relay_THT:Relay_DPDT_Omron_G6S-2", 60, 110, 0),
    ("bypass", "K3", "Relay:G6S-2", "G6S-2 DC5 (terminators IBUS1)", "Relay_THT:Relay_DPDT_Omron_G6S-2", 60, 170, 0),
    ("bypass", "K4", "Relay:G6S-2", "G6S-2 DC5 (terminators IBUS2)", "Relay_THT:Relay_DPDT_Omron_G6S-2", 60, 230, 0),
    ("bypass", "R20", "Device:R", "120R (car IBUS1 term)", R, 140, 160, 0),
    ("bypass", "R21", "Device:R", "120R (ICC IBUS1 term)", R, 140, 180, 0),
    ("bypass", "R22", "Device:R", "120R (car IBUS2 term)", R, 140, 220, 0),
    ("bypass", "R23", "Device:R", "120R (ICC IBUS2 term)", R, 140, 240, 0),
    ("bypass", "U6", "Transistor_Array:ULN2003A", "ULN2003A", SOIC16, 250, 120, 0),
    # ---------------- mcu ----------------
    ("mcu", "U7", "icc_gateway:Teensy4.1_gw", "Teensy 4.1", "teensy:Teensy41", 120, 120, 0),
    ("mcu", "U8", "Interface_CAN_LIN:MCP2517FD-xSL", "MCP2518FD-E/SL", SOIC14, 300, 70, 0),
    ("mcu", "Y1", "Device:Crystal_GND24", "20MHz 3225", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", 350, 70, 0),
    ("mcu", "C20", "Device:C", "15pF", C0603, 340, 100, 0),
    ("mcu", "C21", "Device:C", "15pF", C0603, 360, 100, 0),
    ("mcu", "C22", "Device:C", "100nF (U8 VDD)", C0603, 300, 120, 0),
    ("mcu", "C23", "Device:C", "10uF (U8 VDD)", C, 315, 120, 0),
    ("mcu", "R30", "Device:R", "100k (KL15 sense)", R, 300, 170, 0),
    ("mcu", "R31", "Device:R", "22k (KL15 sense)", R, 320, 170, 0),
    ("mcu", "C24", "Device:C", "10nF (KL15 sense)", C0603, 340, 170, 0),
    ("mcu", "R32", "Device:R", "1k", R, 300, 200, 0),
    ("mcu", "R33", "Device:R", "1k", R, 320, 200, 0),
    ("mcu", "R34", "Device:R", "1k", R, 340, 200, 0),
    ("mcu", "D20", "Device:LED", "LED green (ACTIVE)", LED, 300, 220, 0),
    ("mcu", "D21", "Device:LED", "LED yellow (CAR bus)", LED, 320, 220, 0),
    ("mcu", "D22", "Device:LED", "LED blue (ICC bus)", LED, 340, 220, 0),
    ("mcu", "BT1", "Device:Battery_Cell", "CR2032 (RTC)", "Battery:BatteryHolder_Keystone_3034_1x20mm", 40, 200, 0),
]

# (sheet, ref, pin, kind, net)
CONN = []
def c(sheet, ref, pin, kind, net=None):
    CONN.append((sheet, ref, str(pin), kind, net))

# ---- power ----
c("power", "F1", 1, "g", "VBATT");        c("power", "F1", 2, "l", "VBATT_F")
c("power", "D1", 2, "l", "VBATT_F");      c("power", "D1", 1, "g", "VIN_PROT")   # A->K
c("power", "D2", 1, "g", "VIN_PROT");     c("power", "D2", 2, "p", "GND")
for r in ("C1", "C2", "C3"):
    c("power", r, 1, "g", "VIN_PROT");    c("power", r, 2, "p", "GND")
c("power", "U1", 2, "g", "VIN_PROT");     c("power", "U1", 1, "p", "GND"); c("power", "U1", 9, "p", "GND")
c("power", "U1", 3, "l", "REG_EN");       c("power", "U1", 4, "nc")
c("power", "U1", 5, "l", "FB");           c("power", "U1", 6, "l", "REG_VCC")
c("power", "U1", 7, "l", "BOOT");         c("power", "U1", 8, "l", "SW")
c("power", "C4", 1, "l", "BOOT");         c("power", "C4", 2, "l", "SW")
c("power", "C5", 1, "l", "REG_VCC");      c("power", "C5", 2, "p", "GND")
c("power", "L1", 1, "l", "SW");           c("power", "L1", 2, "p", "+5V")
for r in ("C6", "C7"):
    c("power", r, 1, "p", "+5V");         c("power", r, 2, "p", "GND")
c("power", "R1", 1, "p", "+5V");          c("power", "R1", 2, "l", "FB")
c("power", "R2", 1, "l", "FB");           c("power", "R2", 2, "p", "GND")
c("power", "R3", 1, "l", "REG_EN");       c("power", "R3", 2, "p", "GND")
c("power", "R4", 1, "g", "KL15");         c("power", "R4", 2, "l", "KL15_R")
c("power", "D3", 2, "g", "INH1");         c("power", "D3", 1, "l", "REG_EN")
c("power", "D4", 2, "g", "INH2");         c("power", "D4", 1, "l", "REG_EN")
c("power", "D5", 2, "l", "KL15_R");       c("power", "D5", 1, "l", "REG_EN")

# ---- can: TJA1043T pins 1 TXD,2 GND,3 VCC,4 RXD,5 VIO,6 EN,7 INH,8 ERR,9 WAKE,10 VBAT,11 SPLIT,12 CANL,13 CANH,14 STB ----
for ref, n, hl, inh, rwake, caps in (("U2", 1, "CAR1", "INH1", "R10", ("C10", "C11", "C12")),
                                     ("U3", 2, "CAR2", "INH2", "R11", ("C13", "C14", "C15"))):
    c("can", ref, 1, "g", f"CAN{n}_TX");  c("can", ref, 4, "g", f"CAN{n}_RX")
    c("can", ref, 2, "p", "GND");         c("can", ref, 3, "p", "+5V");  c("can", ref, 5, "p", "+3V3")
    c("can", ref, 6, "g", f"{hl}_EN");    c("can", ref, 14, "g", f"{hl}_STBN"); c("can", ref, 8, "g", f"{hl}_ERRN")
    c("can", ref, 7, "g", inh);           c("can", ref, 9, "l", f"{hl}_WAKE")
    c("can", ref, 10, "g", "VIN_PROT");   c("can", ref, 11, "nc")
    c("can", ref, 12, "g", f"{hl}_L");    c("can", ref, 13, "g", f"{hl}_H")
    c("can", rwake, 1, "g", "KL15");      c("can", rwake, 2, "l", f"{hl}_WAKE")
    for cap, rail in zip(caps, ("+5V", "+3V3", "VIN_PROT")):
        c("can", cap, 1, "p" if rail != "VIN_PROT" else "g", rail); c("can", cap, 2, "p", "GND")
# TJA1051T/3: 1 TXD,2 GND,3 VCC,4 RXD,5 VIO,6 CANL,7 CANH,8 S
for ref, n, hl, caps in (("U4", 3, "ICC1", ("C16", "C17")), ("U5", 4, "ICC2", ("C18", "C19"))):
    c("can", ref, 1, "g", f"CAN{n}_TX");  c("can", ref, 4, "g", f"CAN{n}_RX")
    c("can", ref, 2, "p", "GND");         c("can", ref, 3, "p", "+5V");  c("can", ref, 5, "p", "+3V3")
    c("can", ref, 8, "p", "GND")
    c("can", ref, 6, "g", f"{hl}_L");     c("can", ref, 7, "g", f"{hl}_H")
    for cap, rail in zip(caps, ("+5V", "+3V3")):
        c("can", cap, 1, "p", rail);      c("can", cap, 2, "p", "GND")
# NUP2105L pins filled in after get_symbol_info (see build script): ESD = (ref, H net, L net)
ESD = (("D10", "CAR1_H", "CAR1_L"), ("D11", "CAR2_H", "CAR2_L"), ("D12", "ICC1_H", "ICC1_L"), ("D13", "ICC2_H", "ICC2_L"))

# ---- bypass: G6S-2 pins 1 coil+, 12 coil-, 4 COM1, 3 NC1, 5 NO1, 9 COM2, 10 NC2, 8 NO2 ----
for ref, hl1, hl2, k in (("K1", "CAR1", "ICC1", "RLY1_K"), ("K2", "CAR2", "ICC2", "RLY2_K")):
    c("bypass", ref, 1, "p", "+5V");      c("bypass", ref, 12, "l", k)
    c("bypass", ref, 4, "g", f"{hl1}_H"); c("bypass", ref, 3, "g", f"{hl2}_H"); c("bypass", ref, 5, "nc")
    c("bypass", ref, 9, "g", f"{hl1}_L"); c("bypass", ref, 10, "g", f"{hl2}_L"); c("bypass", ref, 8, "nc")
for ref, car, icc, rc, ri, k in (("K3", "CAR1", "ICC1", "R20", "R21", "RLY3_K"), ("K4", "CAR2", "ICC2", "R22", "R23", "RLY4_K")):
    c("bypass", ref, 1, "p", "+5V");      c("bypass", ref, 12, "l", k)
    c("bypass", ref, 4, "g", f"{car}_H"); c("bypass", ref, 5, "l", f"{car}_TERM"); c("bypass", ref, 3, "nc")
    c("bypass", ref, 9, "g", f"{icc}_H"); c("bypass", ref, 8, "l", f"{icc}_TERM"); c("bypass", ref, 10, "nc")
    c("bypass", rc, 1, "l", f"{car}_TERM"); c("bypass", rc, 2, "g", f"{car}_L")
    c("bypass", ri, 1, "l", f"{icc}_TERM"); c("bypass", ri, 2, "g", f"{icc}_L")
# ULN2003A: I1..I7 = 1..7, GND 8, COM 9, O7..O1 = 10..16
for i in range(1, 5):
    c("bypass", "U6", i, "g", f"RLY{i}");  c("bypass", "U6", 17 - i, "l", f"RLY{i}_K")
for i in range(5, 8):
    c("bypass", "U6", i, "nc");            c("bypass", "U6", 17 - i, "nc")
c("bypass", "U6", 8, "p", "GND");          c("bypass", "U6", 9, "p", "+5V")

# ---- mcu: Teensy 4.1 (symbol pin numbers from teensy:Teensy4.1) ----
T = {  # symbol pin number -> net/kind
    1: ("p", "GND"), 34: ("p", "GND"), 47: ("p", "GND"), 52: ("p", "GND"), 58: ("p", "GND"), 59: ("p", "GND"), 64: ("p", "GND"),
    48: ("p", "+5V"), 46: ("p", "+3V3"),   # 15/51 are the same 3V3 rail: left unconnected (NC) so ERC sees one driver
    50: ("l", "VBAT_RTC"),
    44: ("g", "CAN1_TX"), 45: ("g", "CAN1_RX"),     # pins 22/23
    3: ("g", "CAN2_TX"), 2: ("g", "CAN2_RX"),       # pins 1/0
    23: ("g", "CAN3_TX"), 22: ("g", "CAN3_RX"),     # pins 31/30
    13: ("g", "SPI_MOSI"), 14: ("g", "SPI_MISO"), 35: ("g", "SPI_SCK"), 12: ("g", "CAN4_CS"), 11: ("g", "CAN4_INT"),  # 11/12/13/10/9
    4: ("g", "RLY1"), 5: ("g", "RLY2"), 6: ("g", "RLY3"), 7: ("g", "RLY4"),   # pins 2..5
    8: ("g", "CAR1_STBN"), 9: ("g", "CAR1_EN"), 10: ("g", "CAR1_ERRN"),        # pins 6,7,8
    36: ("g", "CAR2_STBN"), 37: ("g", "CAR2_EN"), 38: ("g", "CAR2_ERRN"),      # pins 14,15,16
    39: ("l", "KL15_SENSE"),                                                  # pin 17 / A3
    16: ("l", "LED1"), 17: ("l", "LED2"), 18: ("l", "LED3"),                   # pins 24,25,26
}
for n in range(1, 68):
    if n in T:
        c("mcu", "U7", n, T[n][0], T[n][1])
    else:
        c("mcu", "U7", n, "nc")
# MCP2518FD (MCP2517FD-xSL symbol): 1 TXCAN,2 RXCAN,3 CLKO,4 nINT,5 OSC2,6 OSC1,7 VSS,8 INT1,9 INT0,10 SCK,11 SDI,12 SDO,13 nCS,14 VDD
c("mcu", "U8", 1, "g", "CAN4_TX"); c("mcu", "U8", 2, "g", "CAN4_RX"); c("mcu", "U8", 3, "nc"); c("mcu", "U8", 4, "g", "CAN4_INT")
c("mcu", "U8", 5, "l", "XTAL2");   c("mcu", "U8", 6, "l", "XTAL1");   c("mcu", "U8", 7, "p", "GND")
c("mcu", "U8", 8, "nc");           c("mcu", "U8", 9, "nc")
c("mcu", "U8", 10, "g", "SPI_SCK"); c("mcu", "U8", 11, "g", "SPI_MOSI"); c("mcu", "U8", 12, "g", "SPI_MISO"); c("mcu", "U8", 13, "g", "CAN4_CS")
c("mcu", "U8", 14, "p", "+3V3")
c("mcu", "Y1", 1, "l", "XTAL1"); c("mcu", "Y1", 3, "l", "XTAL2"); c("mcu", "Y1", 2, "p", "GND"); c("mcu", "Y1", 4, "p", "GND")
c("mcu", "C20", 1, "l", "XTAL1"); c("mcu", "C20", 2, "p", "GND")
c("mcu", "C21", 1, "l", "XTAL2"); c("mcu", "C21", 2, "p", "GND")
for r in ("C22", "C23"):
    c("mcu", r, 1, "p", "+3V3"); c("mcu", r, 2, "p", "GND")
c("mcu", "R30", 1, "g", "KL15"); c("mcu", "R30", 2, "l", "KL15_SENSE")
c("mcu", "R31", 1, "l", "KL15_SENSE"); c("mcu", "R31", 2, "p", "GND")
c("mcu", "C24", 1, "l", "KL15_SENSE"); c("mcu", "C24", 2, "p", "GND")
for r, d, n in (("R32", "D20", 1), ("R33", "D21", 2), ("R34", "D22", 3)):
    c("mcu", r, 1, "l", f"LED{n}"); c("mcu", r, 2, "l", f"LED{n}_K")
    c("mcu", d, 2, "l", f"LED{n}_K"); c("mcu", d, 1, "p", "GND")   # LED: 1=K, 2=A
c("mcu", "BT1", 1, "l", "VBAT_RTC"); c("mcu", "BT1", 2, "p", "GND")  # Battery_Cell: 1 = +, 2 = - (verify)
