import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Metadata } from "next";
import Nav from "@/components/Nav";
import SampleBanner from "@/components/SampleBanner";

export const metadata: Metadata = {
  title: "Worldmodel",
  description: "Explore, compare and map data about every country, region and bloc.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        <SampleBanner />
        <main>{children}</main>
      </body>
    </html>
  );
}
