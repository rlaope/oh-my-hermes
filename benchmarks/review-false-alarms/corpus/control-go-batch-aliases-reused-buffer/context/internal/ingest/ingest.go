package ingest

import "io"

type Source interface {
	// Next appends up to n records to buf and returns it; io.EOF at the end.
	Next(buf []Record, n int) ([]Record, error)
}

func Ingest(src Source, b *Batcher) error {
	buf := make([]Record, 0, 64)
	for {
		var err error
		buf, err = src.Next(buf[:0], 64)
		b.Add(buf)
		if b.Len() >= 500 {
			if ferr := b.Flush(); ferr != nil {
				return ferr
			}
		}
		if err == io.EOF {
			return b.Flush()
		}
		if err != nil {
			return err
		}
	}
}
