/** @type {import('next').NextConfig} */
const fastapiOrigin = (
  process.env.FASTAPI_INTERNAL_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

const nextConfig = {
  /**
   * Proxy API calls through Next so the browser only talks to localhost:3000.
   * Default frontend uses `/fastapi/...` (see lib/api.ts). Set NEXT_PUBLIC_API_URL
   * to skip the proxy and call FastAPI directly.
   */
  async rewrites() {
    return [
      {
        source: "/fastapi/:path*",
        destination: `${fastapiOrigin}/:path*`,
      },
    ];
  },
};

export default nextConfig;
