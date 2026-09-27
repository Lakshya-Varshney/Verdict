/** @type {import('next').NextConfig} */
const API_INTERNAL = process.env.API_INTERNAL_URL || "http://localhost:8000";

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  devIndicators: { position: "bottom-right" },
  // Same-origin proxy to FastAPI => no CORS pain in docker compose.
  // Browser calls /api/* , Next forwards to the backend service.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_INTERNAL}/:path*` },
    ];
  },
  // Swagger UI uses relative asset URLs, so send people to the proxied /api/docs instead of rewriting in place.
  async headers() {
    return [
      { source: "/:path*", headers: [{ key: "X-Content-Type-Options", value: "nosniff" }, { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" }] },
      // the app itself must not be framed by other sites; the embeddable gallery (/embed/*, /api/embed/*) is meant to be
      { source: "/((?!embed/|api/).*)", headers: [{ key: "X-Frame-Options", value: "SAMEORIGIN" }, { key: "Content-Security-Policy", value: "frame-ancestors 'self'" }] },
    ];
  },
  async redirects() {
    return [
      { source: "/backend-docs", destination: "/api/docs", permanent: false },
      { source: "/backend-openapi.json", destination: "/api/openapi.json", permanent: false },
    ];
  },
};
export default nextConfig;
