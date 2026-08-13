import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The dev server only trusts the hostname it was started on (localhost).
  // Loading the site via http://127.0.0.1:3000 counts as a *different*
  // origin, so Next rejects its client-side chunk requests with a 403 and
  // client components silently never hydrate — the page renders fine but
  // nothing interactive works. Trusting 127.0.0.1 too makes both spellings
  // of "this machine" behave the same. Dev-only setting; ignored in
  // production builds.
  allowedDevOrigins: ["127.0.0.1"],

  turbopack: {
    // Pin the workspace root to this directory. Without it, Turbopack walks
    // up looking for a lockfile, finds an unrelated package-lock.json in the
    // user's home directory, and warns about it on every build.
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
