package retry

import (
	"context"
	"time"
)

func Do(ctx context.Context, p Policy, op func(context.Context) error) error {
	var err error
	for attempt := 0; attempt < p.maxAttempts; attempt++ {
		if err = op(ctx); err == nil {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(Delay(p.base, p.max, attempt)):
		}
	}
	return err
}
