import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 8011,
    proxy: {
      '/api/ai/chat/stream': {
        target: 'http://localhost:8010',
        changeOrigin: true,
        timeout: 180000,
      },
      '/api': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8010',
        ws: true,
      },
      '/reports': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['chart.js', 'chartjs-adapter-date-fns', 'chartjs-plugin-zoom'],
        },
      },
    },
  },
});
