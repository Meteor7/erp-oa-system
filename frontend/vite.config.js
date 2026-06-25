import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import frappeui from "frappe-ui/vite";
import path from "path";

export default defineConfig({
  base: "/assets/rayher_hr_payroll/frontend/",
  plugins: [
    frappeui({
      frappeProxy: false,
      lucideIcons: true,
      buildConfig: {
        indexHtmlPath: "../rayher_hr_payroll/www/rayher.html",
      },
    }),
    vue(),
  ],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: {
    outDir: "../rayher_hr_payroll/public/frontend",
    emptyOutDir: true,
    target: "es2018",
    sourcemap: false,
  },
});
