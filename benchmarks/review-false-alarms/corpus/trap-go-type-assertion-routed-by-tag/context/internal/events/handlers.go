package events

import "fmt"

func handleOrder(l *Ledger, ev Event) error {
	order := ev.Payload.(*Order)
	l.Add(order.Account, order.AmountCents)
	return nil
}

func handleRefund(l *Ledger, ev Event) error {
	refund := ev.Payload.(*Refund)
	if refund.AmountCents <= 0 {
		return fmt.Errorf("refund %s: amount must be positive", refund.ID)
	}
	l.Add(refund.Account, -refund.AmountCents)
	return nil
}
