// Cross-platform: run a Next.js command with NEXT_PUBLIC_USE_FIXTURES=1 (no cross-env needed).
//   npm run dev:fixtures   |   npm run build:fixtures && npm run start
import { spawn } from "node:child_process";

const args = process.argv.slice(2);
const child = spawn("npx", ["next", ...args], {
  stdio: "inherit",
  shell: true,
  env: { ...process.env, NEXT_PUBLIC_USE_FIXTURES: "1" },
});
child.on("exit", (code) => process.exit(code ?? 0));
