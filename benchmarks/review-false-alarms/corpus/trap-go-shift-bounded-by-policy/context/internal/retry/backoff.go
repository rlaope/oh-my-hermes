package retry

import "time"

// Delay is the wait before retry number attempt (0-based): base doubled per
// attempt, never more than max.
func Delay(base, max time.Duration, attempt int) time.Duration {
	d := base << attempt
	if d > max {
		return max
	}
	return d
}
