import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = defineConfig([
  // Next.js + React + React Hooks (incl. React Compiler rules) for JS/JSX.
  ...nextVitals,
  {
    // Without TypeScript these are our safety net against typos and dead code.
    rules: {
      "no-unused-vars": ["warn", { args: "after-used", argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" }],
      "no-undef": "error",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
  ]),
]);

export default eslintConfig;
