import type { NextConfig } from "next";

const nextConfig: NextConfig = {
    // standalone 输出，便于 Docker 部署（.next/standalone）
    output: "standalone",
};

export default nextConfig;
