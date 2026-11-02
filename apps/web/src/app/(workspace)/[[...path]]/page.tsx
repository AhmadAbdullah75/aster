import { notFound } from "next/navigation";

export default async function Page({
  params,
}: {
  params: Promise<{ path?: string[] }>;
}) {
  const parts = (await params).path || [];
  const screen = parts[0] || "chat";
  if (
    ![
      "chat",
      "projects",
      "documents",
      "tasks",
      "notes",
      "memories",
      "settings",
    ].includes(screen) ||
    parts.length > (screen === "chat" ? 2 : 1)
  )
    notFound();
  return null;
}
