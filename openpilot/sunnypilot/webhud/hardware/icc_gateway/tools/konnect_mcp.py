#!/usr/bin/env python3
"""Minimal MCP client for the Konnect KiCad server.

Usage:
  konnect_mcp.py tools                      # list tools (name + first line of description)
  konnect_mcp.py tool <name>                # full schema of one tool
  konnect_mcp.py call <name> '<json args>'  # call a tool
  konnect_mcp.py calls <file.jsonl>         # run many calls from a JSONL file: {"name":..., "args":{...}}

Transport: if KONNECT_HTTP (e.g. http://127.0.0.1:PORT/mcp) is set, use streamable HTTP;
otherwise spawn the binary over stdio with the plugin's settings.json.
"""
import json, os, sys, subprocess, threading, queue, urllib.request

PLUGIN = os.path.expanduser("~/Documents/KiCad/10.0/3rdparty/plugins/com_github_mixelpixx_konnect")
BIN = os.path.join(PLUGIN, "bin", "konnect")
SETTINGS = os.path.join(PLUGIN, "settings.json")


ALL_TOOLSETS = ["project","editor_navigation","sch_components","sch_wiring","sch_bus","sch_analysis","sch_batch","sch_export","sch_hierarchy","pcb_board","pcb_components","pcb_routing","placement","pcb_export","library","integration","verification","config","design_review","templates","manufacturing"]


class Stdio:
    def __init__(self):
        args = [BIN]
        cfg = os.environ.get("KONNECT_CONFIG", SETTINGS)
        if os.path.exists(cfg):
            args += ["--config", cfg]
        self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=open(os.environ.get("KONNECT_STDERR", "/dev/null"), "ab"), bufsize=0)
        self.q = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self.n = 0

    def _reader(self):
        for line in self.p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self.q.put(json.loads(line))
            except Exception:
                pass

    def send(self, msg):
        self.p.stdin.write((json.dumps(msg) + "\n").encode())
        self.p.stdin.flush()

    def request(self, method, params=None, timeout=600):
        self.n += 1
        rid = self.n
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        while True:
            m = self.q.get(timeout=timeout)
            if m.get("id") == rid:
                return m

    def notify(self, method, params=None):
        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


class Http:
    def __init__(self, url):
        self.url = url
        self.sid = None
        self.n = 0

    def _post(self, msg):
        data = json.dumps(msg).encode()
        req = urllib.request.Request(self.url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        if self.sid:
            req.add_header("Mcp-Session-Id", self.sid)
        resp = urllib.request.urlopen(req, timeout=600)
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self.sid = sid
        body = resp.read().decode()
        ctype = resp.headers.get("Content-Type", "")
        if "text/event-stream" in ctype:
            out = None
            for line in body.splitlines():
                if line.startswith("data:"):
                    try:
                        out = json.loads(line[5:].strip())
                    except Exception:
                        pass
            return out
        return json.loads(body) if body.strip() else None

    def request(self, method, params=None, timeout=600):
        self.n += 1
        return self._post({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})

    def notify(self, method, params=None):
        self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self):
        pass


def connect():
    url = os.environ.get("KONNECT_HTTP")
    t = Http(url) if url else Stdio()
    r = t.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                 "clientInfo": {"name": "claude-code-bash", "version": "0.1"}})
    t.notify("notifications/initialized")
    return t, r


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tools"
    t, init = connect()
    try:
        if cmd == "init":
            print(json.dumps(init, indent=1))
        elif cmd == "tools":
            if len(sys.argv) > 2:
                t.request("tools/call", {"name": "load_toolset", "arguments": {"name": sys.argv[2].split(",")}})
            tools = []
            cursor = None
            while True:
                r = t.request("tools/list", {"cursor": cursor} if cursor else {})
                res = r.get("result", {})
                tools += res.get("tools", [])
                cursor = res.get("nextCursor")
                if not cursor:
                    break
            for tl in tools:
                d = (tl.get("description") or "").strip().splitlines()
                print(f"{tl['name']}: {d[0] if d else ''}")
            print(f"# {len(tools)} tools", file=sys.stderr)
        elif cmd == "tool":
            t.request("tools/call", {"name": "load_toolset", "arguments": {"name": ALL_TOOLSETS}})
            name = sys.argv[2]
            cursor = None
            while True:
                r = t.request("tools/list", {"cursor": cursor} if cursor else {})
                res = r.get("result", {})
                for tl in res.get("tools", []):
                    if tl["name"] == name:
                        print(json.dumps(tl, indent=1))
                        return
                cursor = res.get("nextCursor")
                if not cursor:
                    break
            print("not found")
        elif cmd == "call":
            name = sys.argv[2]
            args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
            r = t.request("tools/call", {"name": name, "arguments": args})
            print(json.dumps(r.get("result", r), indent=1))
        elif cmd == "calls":
            t.request("tools/call", {"name": "load_toolset", "arguments": {"name": ALL_TOOLSETS}})
            for line in open(sys.argv[2]):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                c = json.loads(line)
                r = t.request("tools/call", {"name": c["name"], "arguments": c.get("args", {})})
                res = r.get("result", r)
                txt = "".join(x.get("text", "") for x in res.get("content", [])) if isinstance(res, dict) else str(res)
                print(f"== {c['name']} {json.dumps(c.get('args', {}))[:160]}\n{txt[:int(os.environ.get("KONNECT_MAX","1500"))]}\n")
    finally:
        t.close()


if __name__ == "__main__":
    main()
