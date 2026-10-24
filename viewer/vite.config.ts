import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // The re-studio local server (viewer/server) owns the case state.
      '/api': 'http://127.0.0.1:7170',
    },
  },
  build: {
    rollupOptions: {
      input: {
        main: 'index.html',
        re: 're.html',
        gif: 'gif-harness.html',
      },
    },
  },
});
