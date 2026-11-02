export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch("/api" + path, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: {
      ...(init?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = "Request failed. Please retry.";
    try {
      const data = await response.json();
      message =
        typeof data.detail === "string"
          ? data.detail
          : Array.isArray(data.detail)
            ? data.detail
                .map((item: { msg?: string }) =>
                  item.msg?.replace(/^Value error, /, ""),
                )
                .filter(Boolean)
                .join(". ") || message
            : message;
    } catch {
      /* response may be plain text */
    }
    throw new ApiError(message, response.status);
  }
  return response.json();
}
export const write = <T>(path: string, body: unknown, method = "POST") =>
  api<T>(path, { method, body: JSON.stringify(body) });

// The sidebar must not silently discard conversations beyond the API's first page.
export async function allResources<T>(path: string): Promise<T[]> {
  const result: T[] = [];
  for (let offset = 0; ; offset += 200) {
    const page = await api<T[]>(
      `${path}${path.includes("?") ? "&" : "?"}limit=200&offset=${offset}`,
    );
    result.push(...page);
    if (page.length < 200) return result;
  }
}

export function validateUpload(file: File, limitMiB: number) {
  if (!/\.(pdf|docx|txt|md)$/i.test(file.name))
    throw new Error("Supported formats: PDF, DOCX, TXT and Markdown.");
  if (!file.size)
    throw new Error("This file is empty. Choose a document with text.");
  if (file.size > limitMiB * 1024 * 1024)
    throw new Error(`${file.name} exceeds the ${limitMiB} MiB per-file limit.`);
}
