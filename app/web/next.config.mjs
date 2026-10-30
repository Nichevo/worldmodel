import os from "node:os";

// The web app talks to the local API through /api, proxied here, so the
// browser never needs to know the API's port. Set WORLDMODEL_API_URL to move it.
const api = process.env.WORLDMODEL_API_URL || "http://127.0.0.1:8000";

// The dev server only hands its scripts to pages opened as localhost, so a page
// opened from another PC on the network loads but never fetches any data. Allow
// this PC's own name and network addresses; WORLDMODEL_ALLOWED_HOSTS (comma
// separated) adds others, such as a DNS name the router gives this PC.
const name = os.hostname().toLowerCase();
const lanHosts = [
  name,
  `${name}.local`,
  `${name}.lan`,
  `${name}.home`,
  ...Object.values(os.networkInterfaces()).flat()
    .filter((i) => i && !i.internal)
    .map((i) => (i.family === "IPv6" ? `[${i.address}]` : i.address)),
  ...(process.env.WORLDMODEL_ALLOWED_HOSTS || "").split(",").map((h) => h.trim()).filter(Boolean),
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: lanHosts,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;
