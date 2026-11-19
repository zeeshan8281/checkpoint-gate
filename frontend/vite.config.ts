import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [tailwindcss()],
  base: "./",
  build: { outDir: "../web", emptyOutDir: true },
  server: { port: 8791, strictPort: true },
});
