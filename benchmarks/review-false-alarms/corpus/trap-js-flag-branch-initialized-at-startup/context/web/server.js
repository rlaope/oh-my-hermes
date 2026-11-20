import http from "node:http";

import { initCheckout, paymentPlan } from "./checkout.js";
import { loadConfig } from "./config.js";

const config = loadConfig(process.env.APP_CONFIG ?? "config/production.json");
initCheckout(config);

const server = http.createServer(async (req, res) => {
  if (req.method !== "POST" || req.url !== "/plan") {
    res.writeHead(404).end();
    return;
  }
  let body = "";
  for await (const chunk of req) body += chunk;
  res.writeHead(200, { "content-type": "application/json" });
  res.end(JSON.stringify(paymentPlan(JSON.parse(body))));
});

server.listen(config.port);
