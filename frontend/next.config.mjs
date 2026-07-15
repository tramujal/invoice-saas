/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Traces and copies only the files actually needed at runtime (plus a
  // generated server.js) into .next/standalone -- lets the Docker runtime
  // image skip installing the full node_modules tree (dominated by the
  // ~97MB `next` package itself). Has no effect on `next dev`/`npm test`.
  output: "standalone",
};

export default nextConfig;
