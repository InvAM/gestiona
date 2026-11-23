const backend = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig = {
  reactCompiler: true,
  output: "standalone",
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // Same-origin proxy to Django so session + CSRF cookies just work.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/_allauth/:path*", destination: `${backend}/_allauth/:path*` },
      { source: "/accounts/:path*", destination: `${backend}/accounts/:path*` },
      { source: "/admin/:path*", destination: `${backend}/admin/:path*` },
      { source: "/admin", destination: `${backend}/admin/` },
      { source: "/static/:path*", destination: `${backend}/static/:path*` },
      { source: "/scim/:path*", destination: `${backend}/scim/:path*` },
      { source: "/media/avatars/:path*", destination: `${backend}/media/avatars/:path*` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
