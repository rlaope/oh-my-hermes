package events

type Ledger struct {
	balances map[string]int64
}

func NewLedger() *Ledger { return &Ledger{balances: map[string]int64{}} }

func (l *Ledger) Add(account string, cents int64) { l.balances[account] += cents }
