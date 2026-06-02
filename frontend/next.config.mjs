/** @type {import('next').NextConfig} */
const backendInternal = process.env.BACKEND_INTERNAL_URL;

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Docker: proxy /api to the backend container so the browser stays same-origin.
  async rewrites() {
    if (!backendInternal) return [];
    return [
      {
        source: "/api/:path*",
        destination: `${backendInternal.replace(/\/$/, "")}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
