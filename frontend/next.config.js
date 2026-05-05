/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  experimental: {
    proxyTimeout: 120_000,
    optimizePackageImports: [
      '@univerjs/presets',
      '@univerjs/preset-sheets-core',
      'lucide-react',
      'recharts',
    ],
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Frame-Options', value: 'ALLOWALL' },
          { key: 'Content-Security-Policy', value: "frame-ancestors 'self' http://localhost:* https://localhost:* https://*.brightspace.com https://*.nyu.edu https://*.azurecontainerapps.io" },
        ],
      },
    ]
  },
  async rewrites() {
    const apiUrl = process.env.API_URL || 'http://localhost:8001'
    return [
      {
        source: '/api/:path*',
        destination: `${apiUrl}/api/:path*`,
      },
      {
        source: '/lti/:path*',
        destination: `${apiUrl}/lti/:path*`,
      },
    ]
  },
}

module.exports = nextConfig
