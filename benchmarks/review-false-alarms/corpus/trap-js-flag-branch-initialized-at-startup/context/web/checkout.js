import { createSplitter } from "./splitter.js";

let settings = null;
let splitter = null;

/** Called once by server.js before the server accepts requests. */
export function initCheckout(config) {
  settings = config;
  if (config.flags.splitPayments) {
    splitter = createSplitter(config.splitPayments);
  }
}

export function paymentPlan(cart) {
  if (settings.flags.splitPayments && cart.payers.length > 1) {
    return splitter.plan(cart.totalCents, cart.payers);
  }
  return [{ payer: cart.payers[0], amountCents: cart.totalCents }];
}
