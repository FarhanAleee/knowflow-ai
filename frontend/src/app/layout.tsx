import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "KnowFlow AI | Company Knowledge Intelligence",
  description:
    "A foundation for a more useful way to explore your company's knowledge.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
