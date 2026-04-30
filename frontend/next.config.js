/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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
