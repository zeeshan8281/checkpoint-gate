import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [tailwindcss()],
  base: "/",
  build: {
    outDir: "../web",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        results: "index.html",
        explorer: "explorer/index.html",
        method: "method/index.html",
      },
    },
  },
  server: { port: 8791, strictPort: true },
});
