/** Incremental UTF-8 / SSE decoder: handles CRLF, multiline data, comments and replay IDs. */
export class SSEParser {
  private decoder = new TextDecoder();
  private buffer = "";
  private data: string[] = [];
  private id = "";
  private type = "message";
  private last = 0;
  constructor(
    private receive: (data: string, id: number, type: string) => void,
    cursor = 0,
  ) {
    this.last = cursor;
  }
  push(bytes: Uint8Array, final = false) {
    this.buffer += this.decoder.decode(bytes, { stream: !final });
    let index: number;
    while ((index = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, index).replace(/\r$/, "");
      this.buffer = this.buffer.slice(index + 1);
      if (line === "") {
        const number = Number(this.id);
        if (this.data.length && (!number || number > this.last)) {
          this.receive(this.data.join("\n"), number, this.type);
          if (number) this.last = number;
        }
        this.data = [];
        this.type = "message";
      } else if (!line.startsWith(":")) {
        const colon = line.indexOf(":");
        const key = colon < 0 ? line : line.slice(0, colon);
        const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (key === "data") this.data.push(value);
        if (key === "id" && !value.includes("\0")) this.id = value;
        if (key === "event") this.type = value;
      }
    }
  }
}
