import { defineConfig } from 'vite';
import { runtimePlugin } from './server/runtime.mjs';
export default defineConfig({ plugins: [runtimePlugin()], server: { host: '127.0.0.1' }, preview: { host: '127.0.0.1' } });
