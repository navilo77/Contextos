import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Context OS — Project context for coding agents",
  description:
    "Turn an application idea into reviewed, validated project documentation for a coding agent.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="bn">
      <body>{children}</body>
    </html>
  );
}
