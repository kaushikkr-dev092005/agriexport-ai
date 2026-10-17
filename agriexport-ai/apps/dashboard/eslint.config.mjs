import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: [".next/**", "node_modules/**", "test-results/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { files: ["components/guide/**/*.{ts,tsx}", "scripts/*.mjs"], languageOptions: { globals: {
    window: "readonly", document: "readonly", localStorage: "readonly", performance: "readonly",
    requestAnimationFrame: "readonly", cancelAnimationFrame: "readonly", getComputedStyle: "readonly",
    IntersectionObserver: "readonly", ResizeObserver: "readonly", NodeFilter: "readonly", console: "readonly",
  } } },
);
