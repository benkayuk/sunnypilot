#!/bin/zsh
# Route the ICC gateway board: Konnect fix-ups -> close editor -> KiCad python DSN export -> Freerouting -> KiCad python SES import -> reopen editor -> DRC/render.
set -u
S=/private/tmp/claude-501/-Users-evanelgin-sunnypilot-1/c8e7b7ca-0e68-4fcb-b273-e015cf12d115/scratchpad
P=/Users/evanelgin/sunnypilot-1/openpilot/sunnypilot/webhud/hardware/icc_gateway
B=$P/icc_gateway.kicad_pcb
R=$P/routing
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
JAVA=/opt/homebrew/opt/openjdk/bin/java
JAR=/Users/evanelgin/Downloads/freerouting-2.5.0.jar
export KICAD_API_SOCKET="ipc:///tmp/kicad/api.sock"
mkdir -p $R
echo "== step 1: skipped"
if false; then
cat > $TMPDIR/rp1.jsonl <<EOF
{"name":"move_component","args":{"board":"$B","reference":"D1","x":101.5,"y":10}}
{"name":"save_project","args":{}}
EOF
KONNECT_MAX=300 KONNECT_STDERR=/dev/null python3 $S/konnect_mcp.py calls $TMPDIR/rp1.jsonl | grep -E '^\{|saved' | cut -c1-120
fi
echo "== step 2: close the PCB editor so the file is free"
pkill -x pcbnew; sleep 5; pgrep -x pcbnew && { echo "pcbnew still running"; exit 1; }
cp $B $R/icc_gateway_prerouting_r2.kicad_pcb
echo "== step 3: export DSN with KiCad's exporter"
$KPY - "$B" "$R/icc_gateway_r2.dsn" <<'EOF'
import sys, pcbnew
board = pcbnew.LoadBoard(sys.argv[1])
out = sys.argv[2]
try:
    ok = pcbnew.ExportSpecctraDSN(board, out)
except TypeError:
    ok = pcbnew.ExportSpecctraDSN(out)
print("ExportSpecctraDSN ->", ok, "nets on board:", board.GetNetCount())
EOF
ls -la $R/icc_gateway_r2.dsn || exit 1
grep -c '(net ' $R/icc_gateway_r2.dsn; grep -E '^\s*\(layer ' $R/icc_gateway_r2.dsn | head -6
grep -A6 '(class ' $R/icc_gateway_r2.dsn | grep -E 'class |width|clearance' | head -20
echo "== step 4: Freerouting"
cd $R
time $JAVA -jar $JAR -de $R/icc_gateway_r2.dsn -do $R/icc_gateway_r2.ses -mp 300 -mt 8 2>&1 | grep -v -E 'WARNING: |final field' | tail -40
ls -la $R/icc_gateway_r2.ses || { echo "no SES produced"; exit 1; }
echo "== step 5: import SES, refill zones, save"
$KPY - "$B" "$R/icc_gateway_r2.ses" <<'EOF'
import sys, pcbnew
board = pcbnew.LoadBoard(sys.argv[1])
ses = sys.argv[2]
try:
    ok = pcbnew.ImportSpecctraSES(board, ses)
except TypeError:
    ok = pcbnew.ImportSpecctraSES(ses)
print("ImportSpecctraSES ->", ok)
tracks = [t for t in board.GetTracks()]
print("tracks+vias:", len(tracks), "vias:", sum(1 for t in tracks if t.GetClass() == "PCB_VIA"))
filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
pcbnew.SaveBoard(sys.argv[1], board)
print("saved", sys.argv[1])
EOF
echo "== step 6: reopen the editor and run DRC"
open -a /Applications/KiCad/KiCad.app/Contents/Applications/pcbnew.app --args "$B"; sleep 20
cat > $TMPDIR/rp6.jsonl <<EOF
{"name":"open_project","args":{}}
{"name":"add_zone","args":{"board":"$B","layer":"F.Cu","net_name":"GND","name":"GND top","points":[{"x":0.5,"y":0.5},{"x":109.5,"y":0.5},{"x":109.5,"y":99.5},{"x":0.5,"y":99.5}],"clearance":0.25,"min_width":0.25,"priority":0}}
{"name":"add_zone","args":{"board":"$B","layer":"B.Cu","net_name":"GND","name":"GND bottom","points":[{"x":0.5,"y":0.5},{"x":109.5,"y":0.5},{"x":109.5,"y":99.5},{"x":0.5,"y":99.5}],"clearance":0.25,"min_width":0.25,"priority":0}}
{"name":"save_project","args":{}}
{"name":"run_drc","args":{"board":"$B","severity":"error","limit":300,"sync_live_board":true,"refill_zones":true}}
EOF
KONNECT_MAX=400000 KONNECT_STDERR=/dev/null python3 $S/konnect_mcp.py calls $TMPDIR/rp6.jsonl > $TMPDIR/rp6.out 2>&1
python3 - <<'EOF'
import os, json
t = open(os.environ['TMPDIR'] + '/rp6.out').read()
for blk in t.split('== ')[1:]:
    name = blk.split(' ')[0]; body = blk.partition('\n')[2].strip()
    try: d = json.loads(body)
    except Exception: print(name, '::', body[:300]); continue
    if name == 'run_drc':
        v = d.get('violations', []); kinds = {}
        for x in v: k = x.get('rule') or x.get('type'); kinds[k] = kinds.get(k, 0) + 1
        print('DRC by rule:', kinds)
        for x in v[:40]:
            if (x.get('rule') or x.get('type')) != 'unconnected_items':
                print(' ', x.get('rule'), '|', x.get('description', '')[:90], '|', [i.get('description', '')[:45] for i in x.get('items', [])][:2])
    else: print(name, '::', json.dumps(d)[:200])
EOF
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb render --output $R/icc_gateway_r2_top.png --side top --width 1600 --height 1460 --quality high "$B" 2>&1 | tail -2
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb render --output $R/icc_gateway_r2_bottom.png --side bottom --width 1600 --height 1460 --quality high "$B" 2>&1 | tail -2
ls -la $R
echo "== done"
