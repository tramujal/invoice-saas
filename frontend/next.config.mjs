/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Traces and copies only the files actually needed at runtime (plus a
  // generated server.js) into .next/standalone -- lets the Docker runtime
  // image skip installing the full node_modules tree (dominated by the
  // ~97MB `next` package itself). Has no effect on `next dev`/`npm test`.
  output: "standalone",
  // Mirrors app.security_headers's own backend headers (see that
  // module's docstring for the full rationale on each one) -- applied
  // here rather than at a reverse-proxy layer, since Vercel serves this
  // app directly and the standalone Docker image has no proxy of its
  // own in front of it either. HSTS is safe to send unconditionally:
  // per RFC 6797 §7.2, browsers ignore Strict-Transport-Security when
  // the response arrived over plain HTTP, so this has no effect during
  // local `next dev`.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "geolocation=(), microphone=(), camera=()" },
          { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
        ],
      },
    ];
  },
};

export default nextConfig;
