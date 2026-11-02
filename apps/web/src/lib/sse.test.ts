import { describe, it, expect } from "vitest";
import { SSEParser } from "./sse";
describe("durable SSE parser", () => {
  it("handles split UTF-8, partial lines, CRLF, multiline data and duplicates", () => {
    const received: string[] = [];
    const parser = new SSEParser((data) => received.push(data));
    const bytes = new TextEncoder().encode(
      ": heartbeat\r\nid: 1\r\nevent: message.delta\r\ndata: café 🌍\r\ndata: second line\r\n\r\nid: 1\ndata: duplicate\n\nid: 2\ndata: final\n\n",
    );
    for (const byte of bytes) parser.push(new Uint8Array([byte]));
    parser.push(new Uint8Array(), true);
    expect(received).toEqual(["café 🌍\nsecond line", "final"]);
  });
  it("honors reconnect cursor", () => {
    const values: string[] = [];
    const p = new SSEParser((d) => values.push(d), 5);
    p.push(
      new TextEncoder().encode("id: 5\ndata: stale\n\nid: 6\ndata: new\n\n"),
    );
    expect(values).toEqual(["new"]);
  });
});
