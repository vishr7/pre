import { defineConfig, loadEnv } from 'vite';
import { runtimePlugin } from './server/runtime.mjs';
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // Keep credentials server-side; only VITE_* variables are exposed by Vite.
  for (const key of ['GEMINI_API_KEY', 'GEMINI_MODEL']) if (!process.env[key] && env[key]) process.env[key] = env[key];
  return { plugins: [runtimePlugin()], server: { host: '127.0.0.1' }, preview: { host: '127.0.0.1' } };
});
