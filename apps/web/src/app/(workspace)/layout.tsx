import { Workspace } from "@/components/workspace";

// Keep navigation, filters and dialogs alive when the selected route changes.
export default function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <Workspace />
      {children}
    </>
  );
}
