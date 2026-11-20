export function createSplitter({ roundingPayer }) {
  return {
    plan(totalCents, payers) {
      const share = Math.floor(totalCents / payers.length);
      const plan = payers.map((payer) => ({ payer, amountCents: share }));
      const rest = totalCents - share * payers.length;
      const index = roundingPayer === "last" ? plan.length - 1 : 0;
      plan[index].amountCents += rest;
      return plan;
    },
  };
}
