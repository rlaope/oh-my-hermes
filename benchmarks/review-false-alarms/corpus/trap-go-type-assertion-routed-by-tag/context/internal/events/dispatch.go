package events

import "fmt"

var handlers = map[string]func(*Ledger, Event) error{
	"order":  handleOrder,
	"refund": handleRefund,
}

func Dispatch(l *Ledger, ev Event) error {
	handle, ok := handlers[ev.Type]
	if !ok {
		return fmt.Errorf("no handler for event type %q", ev.Type)
	}
	return handle(l, ev)
}
