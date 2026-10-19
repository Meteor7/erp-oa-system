import { createApp } from "vue";
import { FrappeUI, setConfig } from "frappe-ui";
import App from "./App.vue";
import router from "./router";
import { enforceCanonicalLocalHost, guardedFrappeRequest, installSessionGuard } from "./lib/sessionGuard";
import "./index.css";
import "./styles/qiheng.css";

if (!enforceCanonicalLocalHost()) {
  setConfig("resourceFetcher", guardedFrappeRequest);
  installSessionGuard();
  const app = createApp(App);
  app.use(router);
  app.use(FrappeUI);
  app.mount("#app");
}
