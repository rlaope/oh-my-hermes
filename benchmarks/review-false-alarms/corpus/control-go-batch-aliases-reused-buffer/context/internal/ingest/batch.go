package ingest

type Record struct {
	Key   string
	Value []byte
}

type Batcher struct {
	pending []Record
	write   func([]Record) error
}

func NewBatcher(write func([]Record) error) *Batcher { return &Batcher{write: write} }

func (b *Batcher) Add(records []Record) {
	if len(b.pending) == 0 {
		b.pending = records
		return
	}
	b.pending = append(b.pending, records...)
}

func (b *Batcher) Len() int { return len(b.pending) }

func (b *Batcher) Flush() error {
	if len(b.pending) == 0 {
		return nil
	}
	err := b.write(b.pending)
	b.pending = nil
	return err
}
