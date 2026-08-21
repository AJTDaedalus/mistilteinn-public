// @ts-check
const eslint = require('@eslint/js');
const { defineConfig } = require('eslint/config');
const tseslint = require('typescript-eslint');
const angular = require('angular-eslint');

module.exports = defineConfig([
  {
    // Generated, gitignored — regenerated from openapi.json via `npm run
    // codegen`, never hand-edited. Not our code to lint.
    ignores: ['src/app/api/api.types.ts'],
  },
  {
    files: ['**/*.ts'],
    extends: [
      eslint.configs.recommended,
      tseslint.configs.recommended,
      tseslint.configs.stylistic,
      angular.configs.tsRecommended,
    ],
    processor: angular.processInlineTemplates,
    rules: {
      '@angular-eslint/directive-selector': [
        'error',
        {
          type: 'attribute',
          prefix: 'app',
          style: 'camelCase',
        },
      ],
      // The codebase predates this linter and already has an established,
      // deliberate multi-prefix convention: 'app-' for shell/global pieces,
      // 'page-' for route-level smart components, 'fairy-' for a few shared
      // components, and bare descriptive names for the rest (see
      // src/app/pages/**, src/app/shared/**). Enforcing a single 'app-'
      // prefix would force a ~38-component rename touching every template
      // usage site — real risk for no functional gain. Only enforce casing.
      '@angular-eslint/component-selector': [
        'error',
        {
          type: 'element',
          prefix: ['app', 'page', 'fairy', ''],
          style: 'kebab-case',
        },
      ],
      // Existing convention: a leading underscore marks a deliberately
      // unused parameter/destructured binding (mock signatures, omit-a-key
      // destructuring) — same convention the backend already uses.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
  {
    // Test doubles legitimately need `any` for loose mock shapes — same
    // relaxation the backend's ruff config gives `tests/**`.
    files: ['**/*.spec.ts'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
  {
    files: ['**/*.html'],
    extends: [angular.configs.templateRecommended, angular.configs.templateAccessibility],
    rules: {
      // `== null` / `!= null` is the standard idiom for "null or undefined"
      // and is intentional throughout the templates; still require === elsewhere.
      '@angular-eslint/template/eqeqeq': ['error', { allowNullOrUndefined: true }],
    },
  },
]);
