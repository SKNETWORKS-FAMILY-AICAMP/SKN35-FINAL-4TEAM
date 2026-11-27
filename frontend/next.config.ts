import type { NextConfig } from "next";
import path from "node:path";

// /api 요청은 FastAPI 로 넘깁니다 (같은 출처라 CORS 설정이 필요 없음).
const api = process.env.SLOTAGENT_API ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  devIndicators: false,
  turbopack: { root: path.resolve(__dirname) },
  rewrites: async () => [{ source: "/api/:path*", destination: `${api}/api/:path*` }],
};
export default nextConfig;
