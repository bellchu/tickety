const manifest = require("../.next/server/app-paths-manifest.json");

const requiredRoutes = [
  "/api/[...path]/route",
  "/tickets/[id]/page",
];

const missingRoutes = requiredRoutes.filter((route) => !(route in manifest));

if (missingRoutes.length > 0) {
  throw new Error(
    `Production build is missing required routes: ${missingRoutes.join(", ")}`,
  );
}

console.log(`Verified production routes: ${requiredRoutes.join(", ")}`);
