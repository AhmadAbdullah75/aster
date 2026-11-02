import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Aster · Your personal workspace",
  description: "Conversations, knowledge and work, connected.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" data-theme="light" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem("nexus-appearance");document.documentElement.dataset.theme=t==="dark"||t==="system"&&matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}catch(e){}})()`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
