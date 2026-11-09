/** @type {import('next').NextConfig} */
module.exports = {
  productionBrowserSourceMaps: true,
  images: {
    remotePatterns: [{ protocol: 'https', hostname: '**' }],
  },
}
