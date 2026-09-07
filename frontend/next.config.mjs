/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone keeps the runtime image small: only the traced dependencies ship,
  // not the whole node_modules tree.
  output: "standalone",
  reactStrictMode: true,
};
export default nextConfig;
