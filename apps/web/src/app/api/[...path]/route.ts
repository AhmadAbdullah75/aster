import { NextRequest } from "next/server";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const base = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";
  const url = new URL("/" + path.map(encodeURIComponent).join("/"), base);
  url.search = request.nextUrl.search;
  const headers = new Headers();
  for (const name of [
    "cookie",
    "content-type",
    "origin",
    "accept",
    "last-event-id",
  ]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    let body: ArrayBuffer | undefined;
    if (!["GET", "HEAD"].includes(request.method) && request.body) {
      const reader = request.body.getReader();
      const parts: Uint8Array[] = [];
      let size = 0;
      while (true) {
        const result = await reader.read();
        if (result.done) break;
        size += result.value.byteLength;
        if (size > 21 * 1024 * 1024) {
          await reader.cancel();
          return Response.json(
            { detail: "Request too large" },
            { status: 413 },
          );
        }
        parts.push(result.value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const part of parts) {
        bytes.set(part, offset);
        offset += part.byteLength;
      }
      body = bytes.buffer;
    }
    const upstream = await fetch(url, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: request.signal,
    });
    const outgoing = new Headers();
    for (const name of [
      "content-type",
      "cache-control",
      "set-cookie",
      "content-disposition",
      "x-accel-buffering",
    ]) {
      const value = upstream.headers.get(name);
      if (value) outgoing.set(name, value);
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: outgoing,
    });
  } catch {
    return Response.json(
      {
        detail:
          "Aster API is unavailable. Start the API and database, then retry.",
      },
      { status: 502 },
    );
  }
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as DELETE,
  proxy as PATCH,
};
