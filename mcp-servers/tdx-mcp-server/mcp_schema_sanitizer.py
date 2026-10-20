#!/usr/bin/env python3
"""
mcp_schema_sanitizer.py - stdio proxy that makes an MCP server's tool schemas
acceptable to the Anthropic API, without touching the server's own code.

It starts your real MCP server as a child process and sits between it and the
Claude desktop app:

  * tools/list  -> rewrites each tool's inputSchema so it passes the API rules
                   (and fixes tool names if needed)
  * tools/call  -> maps the sanitized tool name / argument names back to the
                   originals before forwarding to your server
  * everything else passes through untouched

What it fixes in each inputSchema
  - property names not matching ^[a-zA-Z0-9_.-]{1,64}$  (e.g. "$mask",
    "dsmfg:MfgItem", "$searchStr") -> renamed ("mask", "dsmfg_MfgItem", ...),
    at every nesting level; arguments are renamed back on the way in
  - local $ref (#/definitions/..., #/$defs/..., #/components/schemas/...)
    -> inlined (cycles cut off), definition blocks removed
  - top-level anyOf / oneOf / allOf -> merged into one flat object schema
  - missing/non-object top-level type -> forced to {"type": "object", ...}
    (a non-object root is wrapped as {"input": <root>} and unwrapped on call)
  - "required" entries that do not exist in "properties" -> dropped
  - tool names not matching ^[a-zA-Z0-9_-]{1,64}$ -> renamed (mapped back)
  - outputSchema removed (servers that declare one but return plain text
    get every call rejected); keep it with --keep-output-schema

Usage (in claude_desktop_config.json, wrap your existing command):

  "3dx": {
    "command": "python",
    "args": ["C:\\path\\to\\mcp_schema_sanitizer.py", "--",
             "<your original command>", "<arg1>", "<arg2>", ...],
    "env": { ...unchanged... }
  }

Options (before the "--"):
  --dump DIR   write tools_original.json / tools_sanitized.json / changes.log
               to DIR each time the tool list is fetched (handy for debugging)
  --check FILE offline mode: read a tools/list JSON (the result object, the
               full JSON-RPC response, or a bare list of tools), print what
               would change, write FILE.sanitized.json, and exit

Standard library only. Python 3.8+.
"""

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading

PROP_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
TOOL_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
COMBINATORS = ("anyOf", "oneOf", "allOf")
DEF_KEYS = ("definitions", "$defs")
MAX_REF_DEPTH = 8
KEEP_OUTPUT_SCHEMA = False


def log(*a):
    print("[sanitizer]", *a, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Name sanitizing
# --------------------------------------------------------------------------

def _short_hash(s, n=6):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]


def clean_name(name, pattern, bad_char_re, taken):
    """Return a valid, unique replacement for `name`."""
    if pattern.match(name) and name not in taken:
        return name
    new = name.lstrip("$@")                      # "$mask" -> "mask"
    new = bad_char_re.sub("_", new)              # "dsmfg:MfgItem" -> "dsmfg_MfgItem"
    new = re.sub(r"_+", "_", new).strip("_") or "p"
    if len(new) > 64:
        new = new[:57] + "_" + _short_hash(name)
    base, i = new, 2
    while new in taken or not pattern.match(new):
        suffix = "_%d" % i
        new = base[:64 - len(suffix)] + suffix
        i += 1
    return new


def clean_prop(name, taken):
    return clean_name(name, PROP_RE, re.compile(r"[^a-zA-Z0-9_.-]"), taken)


def clean_tool(name, taken):
    return clean_name(name, TOOL_RE, re.compile(r"[^a-zA-Z0-9_-]"), taken)


# --------------------------------------------------------------------------
# Schema sanitizing
#
# sanitize() returns (new_schema, rmap). rmap describes how to turn the
# sanitized argument object back into what the server expects:
#   {"p": {new_name: [old_name, child_rmap]}, "i": items_rmap, "a": addl_rmap}
# --------------------------------------------------------------------------

def _empty_map():
    return {"p": {}, "i": None, "a": None}


def _merge_maps(a, b):
    if a is None:
        return b
    if b is None:
        return a
    out = {"p": dict(a["p"]), "i": _merge_maps(a["i"], b["i"]),
           "a": _merge_maps(a["a"], b["a"])}
    for k, (old, sub) in b["p"].items():
        if k in out["p"]:
            out["p"][k] = [out["p"][k][0], _merge_maps(out["p"][k][1], sub)]
        else:
            out["p"][k] = [old, sub]
    return out


def _is_trivial(m):
    if m is None:
        return True
    if m["i"] is not None and not _is_trivial(m["i"]):
        return False
    if m["a"] is not None and not _is_trivial(m["a"]):
        return False
    return all(new == old and _is_trivial(sub) for new, (old, sub) in m["p"].items())


def _resolve_ref(ref, root):
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


class Sanitizer:
    def __init__(self, root, changes):
        self.root = root
        self.changes = changes

    def run(self, schema, path, active=()):
        if not isinstance(schema, dict):
            # e.g. `true`, or garbage -> accept anything
            return ({} if schema is True or schema is None else schema), None

        s = dict(schema)

        # Inline local $ref
        if "$ref" in s:
            ref = s.pop("$ref")
            target = _resolve_ref(ref, self.root)
            if target is None:
                self.changes.append("%s: dropped unresolvable $ref %s" % (path, ref))
            elif ref in active or len(active) >= MAX_REF_DEPTH:
                self.changes.append("%s: cut recursive $ref %s (accepts any object)" % (path, ref))
                s.setdefault("type", "object")
            else:
                self.changes.append("%s: inlined $ref %s" % (path, ref))
                merged = dict(copy.deepcopy(target))
                merged.update(s)          # sibling keywords win
                return self.run(merged, path, active + (ref,))

        for k in DEF_KEYS:
            if k in s:
                s.pop(k)

        rmap = _empty_map()

        # properties
        if isinstance(s.get("properties"), dict):
            new_props, taken = {}, set()
            for old, sub in s["properties"].items():
                new = clean_prop(old, taken)
                taken.add(new)
                if new != old:
                    self.changes.append("%s: renamed property %r -> %r" % (path, old, new))
                sub_s, sub_m = self.run(sub, "%s.%s" % (path, new), active)
                new_props[new] = sub_s
                rmap["p"][new] = [old, sub_m]
            s["properties"] = new_props
            if isinstance(s.get("required"), list):
                back = {old: new for new, (old, _) in rmap["p"].items()}
                req = []
                for r in s["required"]:
                    if r in back:
                        req.append(back[r])
                    else:
                        self.changes.append("%s: dropped required %r (no such property)" % (path, r))
                s["required"] = req
                if not req:
                    s.pop("required")
        elif "properties" in s:
            s.pop("properties")

        # array items
        if "items" in s:
            if isinstance(s["items"], list):      # tuple form -> loosen
                s["items"] = {}
                self.changes.append("%s: replaced tuple-style items with {}" % path)
            else:
                s["items"], rmap["i"] = self.run(s["items"], path + "[]", active)

        # additionalProperties schema
        if isinstance(s.get("additionalProperties"), dict):
            s["additionalProperties"], rmap["a"] = self.run(
                s["additionalProperties"], path + "{*}", active)

        # nested combinators: sanitize each branch, merge their maps
        for comb in COMBINATORS:
            if isinstance(s.get(comb), list):
                branches = []
                for i, br in enumerate(s[comb]):
                    b_s, b_m = self.run(br, "%s<%s%d>" % (path, comb, i), active)
                    branches.append(b_s)
                    rmap = _merge_maps(rmap, b_m)
                s[comb] = branches

        return s, (None if _is_trivial(rmap) else rmap)


def _flatten_root(s, changes):
    """Turn a top-level anyOf/oneOf/allOf into one object schema."""
    for comb in COMBINATORS:
        if comb not in s:
            continue
        branches = s.pop(comb)
        props, req_sets = dict(s.get("properties") or {}), []
        for br in branches:
            if not isinstance(br, dict):
                continue
            for k, v in (br.get("properties") or {}).items():
                if k in props and props[k] != v:
                    # same name, different shapes -> accept either
                    props[k] = {"anyOf": [props[k], v]}
                else:
                    props[k] = v
            req_sets.append(set(br.get("required") or []))
        if props:
            s["properties"] = props
        base_req = set(s.get("required") or [])
        if comb == "allOf":
            extra = set().union(*req_sets) if req_sets else set()
        else:   # anyOf/oneOf: only what every branch requires
            extra = set.intersection(*req_sets) if req_sets else set()
        req = sorted(base_req | extra)
        if req:
            s["required"] = req
        else:
            s.pop("required", None)
        changes.append("<root>: flattened top-level %s (%d branches)" % (comb, len(branches)))
    return s


def sanitize_input_schema(schema):
    """Return (new_schema, rmap, changes)."""
    changes = []
    if not isinstance(schema, dict):
        changes.append("<root>: missing schema -> empty object")
        return {"type": "object", "properties": {}}, None, changes

    root = copy.deepcopy(schema)
    # Resolve a top-level $ref first so we can inspect the real root
    if "$ref" in root:
        tgt = _resolve_ref(root["$ref"], schema)
        if isinstance(tgt, dict):
            changes.append("<root>: inlined top-level $ref %s" % root["$ref"])
            r = dict(copy.deepcopy(tgt))
            for k, v in root.items():
                if k != "$ref":
                    r[k] = v
            root = r

    wrap = False
    root_type = root.get("type")
    looks_object = (root_type == "object" or "properties" in root
                    or any(c in root for c in COMBINATORS)) and root_type in (None, "object")
    if not looks_object:
        changes.append("<root>: non-object root (type=%r) wrapped as {input: ...}" % root_type)
        defs = {k: root.pop(k) for k in DEF_KEYS if k in root}
        root = {"type": "object", "properties": {"input": root}, "required": ["input"]}
        root.update(defs)
        wrap = True
    else:
        root = _flatten_root(root, changes)
        if root.get("type") != "object":
            changes.append("<root>: set type to object")
            root["type"] = "object"

    sanitized, rmap = Sanitizer(schema, changes).run(root, "<root>")
    # Drop JSON-Schema meta keys at the root that some validators dislike
    for k in ("$schema", "$id"):
        if sanitized.pop(k, None) is not None:
            changes.append("<root>: removed %s" % k)
    sanitized.setdefault("properties", {})
    if wrap:
        rmap = {"wrap": True, "map": rmap}
    return sanitized, rmap, changes


# --------------------------------------------------------------------------
# Restoring arguments
# --------------------------------------------------------------------------

def restore(value, rmap):
    if rmap is None:
        return value
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in rmap["p"]:
                old, sub = rmap["p"][k]
                out[old] = restore(v, sub)
            else:
                out[k] = restore(v, rmap["a"]) if rmap["a"] else v
        return out
    if isinstance(value, list) and rmap["i"] is not None:
        return [restore(v, rmap["i"]) for v in value]
    return value


def restore_args(args, rmap):
    if rmap is None:
        return args
    if isinstance(rmap, dict) and rmap.get("wrap"):
        inner = (args or {}).get("input")
        return restore(inner, rmap["map"])
    return restore(args or {}, rmap)


# --------------------------------------------------------------------------
# Tool list handling
# --------------------------------------------------------------------------

class ToolTable:
    def __init__(self):
        self.lock = threading.Lock()
        self.name_back = {}     # sanitized tool name -> original
        self.arg_maps = {}      # sanitized tool name -> rmap
        self.taken = set()

    def sanitize_tools(self, tools):
        out, report = [], []
        with self.lock:
            for t in tools:
                if not isinstance(t, dict):
                    continue
                t = dict(t)
                orig_name = t.get("name", "")
                # reuse a previous mapping for the same original name
                prev = next((n for n, o in self.name_back.items() if o == orig_name), None)
                if prev:
                    new_name = prev
                else:
                    new_name = clean_tool(orig_name, self.taken)
                    self.taken.add(new_name)
                    self.name_back[new_name] = orig_name
                schema_key = "inputSchema" if "inputSchema" in t or "input_schema" not in t else "input_schema"
                new_schema, rmap, changes = sanitize_input_schema(t.get(schema_key))
                t[schema_key] = new_schema
                # Servers that declare an outputSchema but reply with plain
                # text (no structuredContent) get every call rejected by the
                # client, so drop the declaration unless --keep-output-schema.
                if not KEEP_OUTPUT_SCHEMA:
                    for k in ("outputSchema", "output_schema"):
                        if t.pop(k, None) is not None:
                            changes.append("removed %s" % k)
                self.arg_maps[new_name] = rmap
                if new_name != orig_name:
                    changes.insert(0, "tool renamed %r -> %r" % (orig_name, new_name))
                    t["name"] = new_name
                if changes:
                    report.append((orig_name, changes))
                out.append(t)
        return out, report

    def lookup(self, name):
        with self.lock:
            return self.name_back.get(name, name), self.arg_maps.get(name)


def format_report(report):
    lines = []
    for name, changes in report:
        lines.append("%s:" % name)
        lines.extend("    " + c for c in changes)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Proxy
# --------------------------------------------------------------------------

class Proxy:
    def __init__(self, cmd, dump_dir=None):
        self.cmd = cmd
        self.dump_dir = dump_dir
        self.table = ToolTable()
        self.pending_list_ids = set()
        self.pending_lock = threading.Lock()
        self.out_lock = threading.Lock()

    def start(self):
        exe = shutil.which(self.cmd[0]) or self.cmd[0]   # resolves npx.cmd etc. on Windows
        log("starting:", exe, *self.cmd[1:])
        self.child = subprocess.Popen(
            [exe] + self.cmd[1:],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
            env=os.environ.copy(), bufsize=0)
        threading.Thread(target=self.pump_from_child, daemon=True).start()
        self.pump_from_client()

    # client (Claude) -> server
    def pump_from_client(self):
        stdin = sys.stdin.buffer
        try:
            for raw in iter(stdin.readline, b""):
                line = raw.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    self.to_child(raw)
                    continue
                for m in (msg if isinstance(msg, list) else [msg]):
                    self.inspect_request(m)
                self.to_child((json.dumps(msg) + "\n").encode("utf-8"))
        finally:
            try:
                self.child.stdin.close()
            except Exception:
                pass
            try:
                self.child.wait(timeout=5)
            except Exception:
                self.child.kill()

    def inspect_request(self, m):
        if not isinstance(m, dict):
            return
        method = m.get("method")
        if method == "tools/list" and "id" in m:
            with self.pending_lock:
                self.pending_list_ids.add(json.dumps(m["id"]))
        elif method == "tools/call":
            params = m.get("params") or {}
            name = params.get("name")
            orig, rmap = self.table.lookup(name)
            if orig != name:
                params["name"] = orig
            if rmap is not None:
                params["arguments"] = restore_args(params.get("arguments"), rmap)
            m["params"] = params

    def to_child(self, data):
        try:
            self.child.stdin.write(data)
            self.child.stdin.flush()
        except (BrokenPipeError, OSError):
            log("server stdin closed")

    # server -> client (Claude)
    def pump_from_child(self):
        for raw in iter(self.child.stdout.readline, b""):
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.to_client(raw if raw.endswith(b"\n") else raw + b"\n")
                continue
            for m in (msg if isinstance(msg, list) else [msg]):
                self.inspect_response(m)
            self.to_client((json.dumps(msg) + "\n").encode("utf-8"))
        log("server exited with code", self.child.wait())
        os._exit(self.child.returncode or 0)

    def inspect_response(self, m):
        if not isinstance(m, dict) or "id" not in m:
            return
        key = json.dumps(m["id"])
        with self.pending_lock:
            if key not in self.pending_list_ids:
                return
            self.pending_list_ids.discard(key)
        result = m.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            return
        original = copy.deepcopy(result["tools"])
        result["tools"], report = self.table.sanitize_tools(result["tools"])
        log("tools/list: %d tools, %d changed" % (len(result["tools"]), len(report)))
        if self.dump_dir:
            self.dump(original, result["tools"], report)

    def dump(self, original, sanitized, report):
        try:
            os.makedirs(self.dump_dir, exist_ok=True)
            with open(os.path.join(self.dump_dir, "tools_original.json"), "w", encoding="utf-8") as f:
                json.dump(original, f, indent=2)
            with open(os.path.join(self.dump_dir, "tools_sanitized.json"), "w", encoding="utf-8") as f:
                json.dump(sanitized, f, indent=2)
            with open(os.path.join(self.dump_dir, "changes.log"), "w", encoding="utf-8") as f:
                f.write(format_report(report) + "\n")
        except Exception as e:
            log("dump failed:", e)

    def to_client(self, data):
        with self.out_lock:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()


# --------------------------------------------------------------------------
# Offline check
# --------------------------------------------------------------------------

def run_check(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    tools = data["tools"] if isinstance(data, dict) else data
    sanitized, report = ToolTable().sanitize_tools(tools)
    print(format_report(report) or "No changes needed.")
    print("\n%d tools, %d changed" % (len(sanitized), len(report)))
    out = path + ".sanitized.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(sanitized, f, indent=2)
    print("Wrote", out)


def main(argv):
    dump_dir, cmd = None, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            cmd = argv[i + 1:]
            break
        if a == "--dump":
            dump_dir = argv[i + 1]
            i += 2
            continue
        if a == "--keep-output-schema":
            global KEEP_OUTPUT_SCHEMA
            KEEP_OUTPUT_SCHEMA = True
            i += 1
            continue
        if a == "--check":
            run_check(argv[i + 1])
            return 0
        if a in ("-h", "--help"):
            print(__doc__)
            return 0
        cmd = argv[i:]       # no "--": treat the rest as the command
        break
    if not cmd:
        print(__doc__, file=sys.stderr)
        return 2
    Proxy(cmd, dump_dir).start()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
