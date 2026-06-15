/**
 * SSE client for the Agent Exchange backend.
 *
 * Native `EventSource` only does GET, but `/api/run` is a POST that streams the
 * job lifecycle back in the response body. So we POST with `fetch`, take the
 * `ReadableStream` body, and hand-parse the SSE wire format
 * (`event: <name>\n data: <json>\n\n`, blank line = dispatch).
 *
 * Returns an async iterator of typed `ExchangeEvent`s plus an `abort()` handle.
 */

import type {
  ExchangeEvent,
  ExchangeEventType,
  RunRequest,
} from "./events";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ||
  "http://localhost:8000";

const KNOWN_EVENT_TYPES: ReadonlySet<string> = new Set<ExchangeEventType>([
  "stage",
  "document",
  "pool",
  "bid",
  "hire",
  "room_message",
  "finding",
  "drift",
  "settle",
  "receipt",
  "done",
  "error",
]);

/** Coerce a raw `{event, data}` SSE frame into a typed ExchangeEvent (or null). */
export function parseFrame(
  eventName: string,
  rawData: string
): ExchangeEvent | null {
  const type = eventName.trim();
  if (!KNOWN_EVENT_TYPES.has(type)) return null;
  let data: unknown;
  try {
    data = JSON.parse(rawData);
  } catch {
    return null;
  }
  // The union is validated structurally downstream; we trust the named-event
  // contract here and cast to the corresponding member.
  return { type, data } as ExchangeEvent;
}

export interface RunHandle {
  events: AsyncGenerator<ExchangeEvent>;
  abort: () => void;
}

/** The locked 429 reasons the backend returns before a live run can stream. */
export type LiveUnavailableReason =
  | "live_busy"
  | "live_cap_reached"
  | "live_unavailable";

const LIVE_REASONS: ReadonlySet<string> = new Set<LiveUnavailableReason>([
  "live_busy",
  "live_cap_reached",
  "live_unavailable",
]);

/** Judge-readable copy per reason (used only as the error message fallback). */
const LIVE_REASON_COPY: Record<LiveUnavailableReason, string> = {
  live_busy: "A live Band room is already in flight.",
  live_cap_reached: "The daily live-run budget has been reached.",
  live_unavailable: "The live backend is unavailable right now.",
};

/** Parse the 429 body `{"error": "live_busy"|…}` into a typed reason. */
async function readLiveReason(res: Response): Promise<LiveUnavailableReason> {
  try {
    const body = (await res.json()) as { error?: string };
    if (body?.error && LIVE_REASONS.has(body.error)) {
      return body.error as LiveUnavailableReason;
    }
  } catch {
    // fall through — a 429 with an unreadable body is still "unavailable"
  }
  return "live_unavailable";
}

/**
 * Start a live job run and stream typed events back.
 *
 * Usage:
 *   const { events, abort } = runJob(req);
 *   for await (const ev of events) { ... }
 */
export function runJob(req: RunRequest): RunHandle {
  const controller = new AbortController();

  async function* generate(): AsyncGenerator<ExchangeEvent> {
    const res = await fetch(`${API_BASE}/api/run`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(req),
      signal: controller.signal,
    });

    if (!res.ok || !res.body) {
      // A 429 (live busy / daily cap / unavailable) is a CLEAN, expected signal:
      // the backend returns it BEFORE streaming, with a typed JSON reason. We
      // surface it as `live_status` on the error event so the Dashboard can fall
      // back to the recorded real run rather than treating it as a hard error.
      let liveStatus: LiveUnavailableReason | undefined;
      if (res.status === 429) {
        liveStatus = await readLiveReason(res);
      }
      yield {
        type: "error",
        data: liveStatus
          ? {
              message: LIVE_REASON_COPY[liveStatus],
              live_status: liveStatus,
            }
          : {
              message: `Backend responded ${res.status} ${res.statusText}. Is ${API_BASE} running?`,
            },
      };
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line (handles \n\n and \r\n\r\n).
        let sep: number;
        while ((sep = nextFrameBoundary(buffer)) !== -1) {
          const rawFrame = buffer.slice(0, sep);
          const boundaryLen = frameBoundaryLen(buffer, sep);
          buffer = buffer.slice(sep + boundaryLen);
          const ev = parseSseFrame(rawFrame);
          if (ev) yield ev;
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  return { events: generate(), abort: () => controller.abort() };
}

/** Index of the next frame boundary (blank line), or -1. */
function nextFrameBoundary(buf: string): number {
  const lf = buf.indexOf("\n\n");
  const crlf = buf.indexOf("\r\n\r\n");
  if (lf === -1) return crlf;
  if (crlf === -1) return lf;
  return Math.min(lf, crlf);
}

function frameBoundaryLen(buf: string, idx: number): number {
  return buf.startsWith("\r\n\r\n", idx) ? 4 : 2;
}

/** Parse one raw SSE frame block into a typed event. */
function parseSseFrame(block: string): ExchangeEvent | null {
  let eventName = "message";
  const dataLines: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith(":")) continue; // comment / heartbeat
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).replace(/^ /, ""));
    }
  }
  if (dataLines.length === 0) return null;
  return parseFrame(eventName, dataLines.join("\n"));
}

/** Fetch a prefilled sample document for a job kind. */
export async function fetchSample(
  kind: string
): Promise<{ title: string; document_text: string; budget_usd?: number } | null> {
  try {
    const res = await fetch(
      `${API_BASE}/api/jobs/sample?kind=${encodeURIComponent(kind)}`,
      { headers: { Accept: "application/json" } }
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}
