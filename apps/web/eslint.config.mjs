import js from '@eslint/js';
import ts from 'typescript-eslint';
import hooks from 'eslint-plugin-react-hooks';
import next from '@next/eslint-plugin-next';
import globals from 'globals';
import { defineConfig, globalIgnores } from 'eslint/config';

export default defineConfig([
  globalIgnores(['.next/**', '.next-e2e/**', 'next-env.d.ts', 'public/pdf-assets/**']),
  js.configs.recommended,
  ...ts.configs.recommended,
  { languageOptions: { globals: { ...globals.browser, ...globals.node } } },
  { files: ['**/*.ts', '**/*.tsx'], rules: { 'no-undef': 'off' } },
  { files: ['src/**/*.tsx'], plugins: { 'react-hooks': hooks, '@next/next': next }, rules: {
    ...hooks.configs.recommended.rules,
    ...next.configs.recommended.rules,
    ...next.configs['core-web-vitals'].rules,
  } },
]);
