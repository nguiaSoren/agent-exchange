/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // No ESLint config is checked into this repo, so don't let the production build
  // block on lint setup/errors. TypeScript type-checking stays ON (tsc is kept
  // clean), so real type safety is still enforced at build time.
  eslint: {
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
