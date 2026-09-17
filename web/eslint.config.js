import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/**", "src/api/generated/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        {
          allowConstantExport: true,
          // Context + Provider + its consumer hook deliberately live in one
          // file (WP-03 convention) - not a Fast Refresh hazard worth splitting
          // the file over.
          allowExportNames: ["useAuth", "useApiClient", "useDiagnosticTraces"],
        },
      ],
      // Server state is fetched through the client; a dropped promise there is a
      // silently stuck screen, so floating promises are an error, not a warning.
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/consistent-type-imports": "error",
    },
  },
  {
    files: ["**/*.test.ts", "**/*.test.tsx"],
    rules: { "@typescript-eslint/unbound-method": "off" },
  },
  // eslint.config.js is a .js file and tsconfig has `allowJs: false`, so it can
  // never be part of the typed project - turn type-aware parsing/rules back
  // off for it rather than fighting a default-project fallback (typescript-eslint's
  // own documented pattern for linting its own config file). Must come last so
  // it overrides the projectService set above.
  {
    files: ["eslint.config.js"],
    extends: [tseslint.configs.disableTypeChecked],
    languageOptions: {
      parserOptions: { projectService: false, project: false },
    },
  },
);
