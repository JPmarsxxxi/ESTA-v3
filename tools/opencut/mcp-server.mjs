#!/usr/bin/env node
// ESTA → OpenCut live-edit MCP server.
//
// Exposes the OpenCut timeline as MCP tools so Claude can edit the live editor in
// natural language. Each tool just POSTs a {cmd,...} to the asset-server's
// command channel (POST /_cmd); the in-editor EstaCmdBridge dispatcher applies
// it (notes/opencut-mcp-build.md). The asset-server + an open editor must be
// running.
//
// Transport: stdio, newline-delimited JSON-RPC 2.0 (the MCP stdio framing).
// Zero deps — Node 18+ global fetch + readline. Register in .mcp.json and
// restart Claude Code so the tools appear.
//
// Walking-skeleton tool: set_clip_duration. Adding a tool = one TOOLS entry +
// one dispatch branch (and the matching case in esta-cmd-bridge.tsx).

import { createInterface } from "node:readline";

const BASE =
  process.env.ESTA_ASSET_URL ||
  `http://localhost:${process.env.ASSET_PORT || 8787}`;
const CMD_URL = `${BASE}/_cmd`;
const STATE_URL = `${BASE}/_state`;
const ACK_URL = `${BASE}/_ack`;
const FRAME_URL = `${BASE}/_frame`;

const SERVER_INFO = { name: "esta-opencut", version: "0.1.0" };

const TOOLS = [
  {
    name: "get_timeline",
    description:
      "Read the live OpenCut timeline — every track and clip with its id, media " +
      "name, start time, duration, source duration, and trim, all in seconds. " +
      "Reflects manual edits too. Call this FIRST to resolve which clip the user " +
      "means (by media name, position, etc.) and to get its id + numbers before " +
      "editing. Returns the latest snapshot the open editor pushed.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "get_frame",
    description:
      "SEE the actual composited video frame at a timeline time (seconds) — " +
      "Ken Burns, transitions, and text overlays all rendered, as a downscaled " +
      "JPEG. Use SELECTIVELY, only when a decision needs eyes: is a cut jarring, " +
      "did a fade/transition land, does a shot match the intended vibe. Returns " +
      "an image. Call get_timeline first to pick meaningful times.",
    inputSchema: {
      type: "object",
      properties: {
        time: {
          type: "number",
          description: "Timeline time in seconds to render and view",
        },
      },
      required: ["time"],
    },
  },
  {
    name: "update_clip",
    description:
      "Edit one clip on the live timeline by its id (from get_timeline). All " +
      "values are in SECONDS. Set `duration` for length; `trim_start`/`trim_end` " +
      "to choose which part of the source plays (e.g. first 10s = trim_start 0, " +
      "duration 10); `start` to move it on the timeline. Omit fields you don't " +
      "want to change.",
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string", description: "Clip id from get_timeline" },
        duration: { type: "number", description: "New duration (s)" },
        trim_start: {
          type: "number",
          description: "Seconds into the source where playback starts",
        },
        trim_end: {
          type: "number",
          description: "Seconds trimmed off the source's end",
        },
        start: { type: "number", description: "New timeline start (s)" },
        volume: {
          type: "number",
          description:
            "Static volume level, 1 = full, 0 = silent (sound-design levels). " +
            "For fades/ducking use animate_clip with property 'volume'.",
        },
      },
      required: ["id"],
    },
  },
  {
    name: "animate_clip",
    description:
      "Keyframe a property on a clip over time to apply editing-principle motion. " +
      "ONE verb covers several: property 'scale' = Ken Burns (e.g. keys 1.0→1.08 " +
      "over the shot); 'opacity' = fade in/out or dip-to-black transitions (0↔1); " +
      "'volume' = audio fades and DUCKING (dip music under voice). keys is " +
      "[{t,v}] where t = seconds INTO the clip and v = the value at that moment; " +
      "ramps are linear between keys. Get the clip id and its duration from " +
      "get_timeline first. Examples — fade in: [{t:0,v:0},{t:0.5,v:1}]; duck " +
      "music: [{t:0,v:1},{t:0.3,v:0.3},{t:5,v:0.3},{t:5.3,v:1}].",
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string", description: "Clip id from get_timeline" },
        property: {
          type: "string",
          enum: [
            "opacity",
            "scale",
            "scaleX",
            "scaleY",
            "positionX",
            "positionY",
            "volume",
          ],
        },
        keys: {
          type: "array",
          description: "Keyframes: each {t: clip-local seconds, v: value}",
          items: {
            type: "object",
            properties: { t: { type: "number" }, v: { type: "number" } },
            required: ["t", "v"],
          },
        },
      },
      required: ["id", "property", "keys"],
    },
  },
  {
    name: "set_clip_duration",
    description:
      "Convenience: set the duration (seconds) of the Nth shot by time on the " +
      "main video spine (1-based). For anything beyond a main-spine shot, prefer " +
      "get_timeline + update_clip.",
    inputSchema: {
      type: "object",
      properties: {
        shot: { type: "integer", minimum: 1 },
        seconds: { type: "number", exclusiveMinimum: 0 },
      },
      required: ["shot", "seconds"],
    },
  },
];

// tool name → builds the {cmd,...} payload posted to the command channel.
const DISPATCH = {
  set_clip_duration: (args) => ({
    cmd: "set_duration",
    shot: args.shot,
    seconds: args.seconds,
  }),
  update_clip: (args) => {
    const patch = {};
    if (args.duration != null) patch.duration = args.duration;
    if (args.trim_start != null) patch.trim_start = args.trim_start;
    if (args.trim_end != null) patch.trim_end = args.trim_end;
    if (args.start != null) patch.start = args.start;
    if (args.volume != null) patch.volume = args.volume;
    return { cmd: "update_clip", id: args.id, patch };
  },
  animate_clip: (args) => ({
    cmd: "animate_clip",
    id: args.id,
    property: args.property,
    keys: args.keys,
  }),
};

async function postCommand(payload) {
  const res = await fetch(CMD_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`asset-server ${res.status}: ${await res.text()}`);
  return res.json(); // { ok, delivered }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Poll the ack channel until the editor reports it handled reqId (or timeout).
// This is what closes the "false success" gap — a command can be delivered yet
// not apply (clip id not found, stale dispatcher). We report the real outcome.
async function waitForAck(reqId, timeoutMs = 2500) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${ACK_URL}?reqId=${encodeURIComponent(reqId)}`);
      const ack = await res.json();
      if (!ack.pending) return ack;
    } catch {
      /* asset-server hiccup — keep polling */
    }
    await sleep(150);
  }
  return null;
}

// Rendering a frame takes longer than an ack (canvas render), so poll longer.
async function waitForFrame(reqId, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${FRAME_URL}?reqId=${encodeURIComponent(reqId)}`);
      const f = await res.json();
      if (!f.pending) return f; // { image } | { error }
    } catch {
      /* keep polling */
    }
    await sleep(200);
  }
  return null;
}

function write(msg) {
  process.stdout.write(JSON.stringify(msg) + "\n");
}

function reply(id, result) {
  write({ jsonrpc: "2.0", id, result });
}

function replyError(id, code, message) {
  write({ jsonrpc: "2.0", id, error: { code, message } });
}

async function handle(msg) {
  const { id, method, params } = msg;

  switch (method) {
    case "initialize":
      reply(id, {
        // Echo the client's protocol version for max compatibility.
        protocolVersion: params?.protocolVersion || "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: SERVER_INFO,
      });
      return;

    case "notifications/initialized":
    case "initialized":
      return; // notification, no response

    case "tools/list":
      reply(id, { tools: TOOLS });
      return;

    case "tools/call": {
      const name = params?.name;
      const args = params?.arguments || {};

      // Read tool — fetch the live timeline snapshot.
      if (name === "get_timeline") {
        try {
          const res = await fetch(STATE_URL);
          const state = await res.json();
          const warn = state._stale
            ? `⚠ STALE — no live editor has pushed state in the last few seconds ` +
              `(age ${state._age_ms ?? "?"}ms). The tab may be closed or on an old ` +
              `build. Do NOT trust clip ids below; open the session's Edit stage first.\n\n`
            : "";
          reply(id, {
            content: [
              { type: "text", text: warn + JSON.stringify(state, null, 2) },
            ],
          });
        } catch (err) {
          reply(id, {
            isError: true,
            content: [
              { type: "text", text: `Failed to read timeline: ${err.message}` },
            ],
          });
        }
        return;
      }

      // Visual sight — ask the editor to render a frame, return it as an image.
      if (name === "get_frame") {
        try {
          const reqId =
            globalThis.crypto?.randomUUID?.() ?? `f${Date.now()}-${Math.random()}`;
          const out = await postCommand({ cmd: "get_frame", time: args.time, reqId });
          if (!out.live) {
            reply(id, {
              isError: true,
              content: [
                {
                  type: "text",
                  text: "No LIVE editor to render from — open the session's Edit stage (localhost:3000/esta/<id>) first.",
                },
              ],
            });
            return;
          }
          const f = await waitForFrame(reqId);
          if (!f) {
            reply(id, {
              isError: true,
              content: [{ type: "text", text: "Frame render timed out (8s)." }],
            });
            return;
          }
          if (f.error) {
            reply(id, {
              isError: true,
              content: [{ type: "text", text: `Frame render failed: ${f.error}` }],
            });
            return;
          }
          const base64 = String(f.image || "").split(",")[1] || "";
          reply(id, {
            content: [
              { type: "text", text: `Composited frame at ${args.time}s (${f.w}x${f.h}):` },
              { type: "image", data: base64, mimeType: "image/jpeg" },
            ],
          });
        } catch (err) {
          reply(id, {
            isError: true,
            content: [{ type: "text", text: `get_frame failed: ${err.message}` }],
          });
        }
        return;
      }

      const build = DISPATCH[name];
      if (!build) {
        replyError(id, -32602, `Unknown tool: ${name}`);
        return;
      }
      try {
        const reqId =
          (globalThis.crypto?.randomUUID?.() ?? `r${Date.now()}-${Math.random()}`);
        const payload = { ...build(args), reqId };
        const out = await postCommand(payload);

        // Gate on `live` (recent heartbeat), NOT `delivered` (counts zombie
        // SSE tabs). If no editor has heartbeat'd recently, refuse honestly
        // instead of sending into a dead tab.
        if (!out.live) {
          reply(id, {
            isError: true,
            content: [
              {
                type: "text",
                text:
                  "No LIVE editor is open (no heartbeat in the last few seconds). " +
                  "Open the session's Edit stage (localhost:3000/esta/<id>) and wait " +
                  "for the timeline to load, then retry.",
              },
            ],
          });
          return;
        }

        // Delivered — now confirm it actually applied.
        const ack = await waitForAck(reqId);
        if (!ack) {
          reply(id, {
            isError: true,
            content: [
              {
                type: "text",
                text:
                  `Command was delivered to ${out.delivered} editor(s) but never ` +
                  `acknowledged. The editor tab is likely running an old build ` +
                  `or is stale — reload the session's workspace (localhost:3000/esta/<id>) and retry.`,
              },
            ],
          });
          return;
        }
        if (!ack.applied) {
          reply(id, {
            isError: true,
            content: [
              { type: "text", text: `Not applied: ${ack.message || "unknown reason"}` },
            ],
          });
          return;
        }
        reply(id, { content: [{ type: "text", text: `Applied: ${ack.message}` }] });
      } catch (err) {
        reply(id, {
          isError: true,
          content: [{ type: "text", text: `Failed: ${err.message}` }],
        });
      }
      return;
    }

    case "ping":
      reply(id, {});
      return;

    default:
      if (id !== undefined) replyError(id, -32601, `Method not found: ${method}`);
  }
}

const rl = createInterface({ input: process.stdin });
rl.on("line", (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  let msg;
  try {
    msg = JSON.parse(trimmed);
  } catch {
    return; // ignore non-JSON lines
  }
  handle(msg).catch((err) => {
    if (msg?.id !== undefined) replyError(msg.id, -32603, String(err));
  });
});
