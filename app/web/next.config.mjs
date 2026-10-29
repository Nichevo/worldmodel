// The web app talks to the local API through /api, proxied here, so the
// browser never needs to know the API's port. Set WORLDMODEL_API_URL to move it.
const api = process.env.WORLDMODEL_API_URL || "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;
