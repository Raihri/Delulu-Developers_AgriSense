import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: path.resolve(__dirname),
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
