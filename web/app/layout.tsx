import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "SMM AI Helper", description: "AI workspace for marketing teams" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="ru"><body>{children}</body></html>; }
