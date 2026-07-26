/**
 * The browser talks to the API at NEXT_PUBLIC_API_URL, which in every real
 * deployment is a DIFFERENT origin than the web app. `connect-src 'self'`
 * alone therefore blocks every fetch and the notifications WebSocket, so the
 * API origin has to be allowed explicitly — both http(s) and ws(s).
 */
function apiConnectSources() {
  const raw = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const url = new URL(raw);
    const wsScheme = url.protocol === "https:" ? "wss:" : "ws:";
    return [url.origin, `${wsScheme}//${url.host}`];
  } catch {
    console.warn(`[next.config] NEXT_PUBLIC_API_URL is not a valid URL: ${raw}`);
    return [];
  }
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  transpilePackages: ["@outreach-os/shared-types"],
  experimental: {
    typedRoutes: false,
  },
  async headers() {
    const csp = [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
      "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
      "font-src 'self' https://fonts.gstatic.com data:",
      "img-src 'self' data: https: blob:",
      ["connect-src 'self'", ...apiConnectSources()].join(" "),
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; ");

    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "geolocation=(), microphone=(), camera=()" },
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
    ];
  },
};

export default nextConfig;