import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgriSense AI",
  description: "Source-grounded Bangladesh farm planning",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="bn">
      <body>{children}</body>
    </html>
  );
}
