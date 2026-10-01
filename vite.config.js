import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  root: "frontend",
  plugins: [react()],
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom"],
          markdown: ["react-markdown", "remark-math", "rehype-katex"],
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8090",
      "/health": "http://127.0.0.1:8090",
    },
  },
});
