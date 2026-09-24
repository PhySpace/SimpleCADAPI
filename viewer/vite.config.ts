import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // The local studio server owns case state and the WebApp RPC boundary.
      '/api': 'http://127.0.0.1:7170',
      '/rpc': 'http://127.0.0.1:7170',
    },
  },
  build: {
    rollupOptions: {
      input: {
        main: 'index.html',
        gif: 'gif-harness.html',
      },
    },
  },
});
