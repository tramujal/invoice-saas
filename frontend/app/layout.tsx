import type { Metadata } from "next";
import { Inter } from "next/font/google";

import "./globals.css";

import { Providers } from "./providers";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Invoicing",
  description: "Minimal invoicing UI",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${inter.className} min-h-dvh`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
