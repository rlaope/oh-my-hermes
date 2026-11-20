package retry

import (
	"fmt"
	"time"
)

// Policy is built only by NewPolicy; its fields are unexported.
type Policy struct {
	maxAttempts int
	base        time.Duration
	max         time.Duration
}

func NewPolicy(maxAttempts int, base, max time.Duration) (Policy, error) {
	if maxAttempts < 1 || maxAttempts > 8 {
		return Policy{}, fmt.Errorf("retry: maxAttempts %d not in 1..8", maxAttempts)
	}
	if base <= 0 || base > 5*time.Second {
		return Policy{}, fmt.Errorf("retry: base %s not in (0, 5s]", base)
	}
	if max < base {
		return Policy{}, fmt.Errorf("retry: max %s below base %s", max, base)
	}
	return Policy{maxAttempts: maxAttempts, base: base, max: max}, nil
}
