import { defineConfig, loadEnv } from 'vite';
import { runtimePlugin } from './server/runtime.mjs';
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // Keep credentials server-side; only VITE_* variables are exposed by Vite.
  for (const key of ['GEMINI_API_KEY', 'GEMINI_MODEL']) if (!process.env[key] && env[key]) process.env[key] = env[key];
  // Iterate and HPC live in the Python backend (uvicorn backend.main:app); forward them so they work
  // with an empty Backend API URL while /api keeps using the built-in local runtime.
  const backend = process.env.PRE_BACKEND_URL || env.PRE_BACKEND_URL || 'http://127.0.0.1:8000';
  const proxy = Object.fromEntries(['/iterate', '/hpc'].map(path => [path, { target: backend, ws: true, changeOrigin: true }]));
  return { plugins: [runtimePlugin()], server: { host: '127.0.0.1', proxy }, preview: { host: '127.0.0.1', proxy } };
});
