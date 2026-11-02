import Link from "next/link";

export default function NotFound() {
  return (
    <main className="full-center">
      <span className="eyebrow">A different direction</span>
      <h1>Page not found</h1>
      <p>This page is unavailable. Your saved work is in your workspace.</p>
      <Link href="/chat" className="button primary">
        Back to workspace
      </Link>
    </main>
  );
}
