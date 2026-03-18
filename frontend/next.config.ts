import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // In production, the frontend calls the backend directly via NEXT_PUBLIC_API_URL.
  // In development, proxy /api/* requests to the local FastAPI backend.
  async rewrites() {
    // Skip rewrites when NEXT_PUBLIC_API_URL is set (production / Vercel)
    if (process.env.NEXT_PUBLIC_API_URL) {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },

  // Allow anime cover images from MAL CDN
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "cdn.myanimelist.net",
      },
    ],
  },
};

export default nextConfig;
