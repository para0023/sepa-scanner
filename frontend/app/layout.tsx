import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import "./globals.css";
import Sidebar from "@/components/layout/Sidebar";

const mono = Geist_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "SEPA Scanner",
  description: "Stock trading scanner & portfolio manager",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className={`${mono.variable} h-full antialiased dark`}>
      <body className="min-h-full flex bg-[#0d1117] text-gray-200">
        <Sidebar />
        <main className="flex-1 md:ml-56 p-4 md:p-6 pt-14 md:pt-6 overflow-auto">{children}</main>
      </body>
    </html>
  );
}
