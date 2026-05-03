/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Cuts the runner image and skips `npm start` boot overhead.
  output: 'standalone',
  // Skip ESLint at build time. Lint locally in CI; baking it into every
  // production image rebuild costs ~10-15s for no runtime benefit.
  eslint: { ignoreDuringBuilds: true },
  // The repo is .jsx today, but pin this so a future stray .ts file can't
  // slow image builds with type-checking.
  typescript: { ignoreBuildErrors: true },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_ORCHESTRATOR_URL || 'http://localhost:7100'}/api/:path*`,
      },
      {
        source: '/demo/:path*',
        destination: `${process.env.NEXT_PUBLIC_ORCHESTRATOR_URL || 'http://localhost:7100'}/demo/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
