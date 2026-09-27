import type { Metadata, Viewport } from "next";
import "@fontsource-variable/instrument-sans";
import "@fontsource/instrument-serif";
import "@fontsource/instrument-serif/400-italic.css";
import "@fontsource-variable/big-shoulders-display";
import "@fontsource-variable/martian-mono";
import "./globals.css";
import { Providers } from "./providers";
import { Chrome } from "@/components/Shell";
import { BRAND } from "@/lib/brand";

export const metadata: Metadata = { title: { default: `${BRAND.name} — judge in the open`, template: `%s · ${BRAND.name}` }, description: BRAND.tagline };
export const viewport: Viewport = { themeColor: "#0a0908" };

const themeInit = `try{var t=localStorage.getItem('verdict.theme');if(t==='paper')document.documentElement.dataset.theme='paper'}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeInit }} /></head>
      <body><Providers><Chrome>{children}</Chrome></Providers></body>
    </html>
  );
}
