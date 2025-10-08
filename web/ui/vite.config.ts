import { defineConfig, loadEnv, type ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  const proxy: Record<string, string | ProxyOptions> = {};
  if (env.VITE_API_BASE) {
    proxy["/api"] = {
      target: env.VITE_API_BASE,
      changeOrigin: true,
      secure: false,
    } satisfies ProxyOptions;
  }
  if (env.VITE_WS_URL) {
    proxy["/ws"] = {
      target: env.VITE_WS_URL,
      ws: true,
      changeOrigin: true,
      secure: false,
    } satisfies ProxyOptions;
  }

  return {
    base: "/static/",
    plugins: [react()],
    server: {
      port: Number(env.VITE_DEV_PORT || 5173),
      host: env.VITE_DEV_HOST || "0.0.0.0",
      proxy,
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
  };
});
