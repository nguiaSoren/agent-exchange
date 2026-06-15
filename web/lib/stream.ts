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
      yield {
        type: "error",
        data: {
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
