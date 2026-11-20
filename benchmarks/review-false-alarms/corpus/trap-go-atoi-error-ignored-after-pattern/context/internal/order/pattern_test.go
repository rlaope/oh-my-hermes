package order

import "testing"

func TestLinePatternQuantityIsOneToFourDigits(t *testing.T) {
	for _, text := range []string{"ABC-1234 x 1", "ABC-1234 x 0007", "ABC-1234 x 9999"} {
		if linePattern.FindStringSubmatch(text) == nil {
			t.Errorf("%q should match", text)
		}
	}
	for _, text := range []string{
		"ABC-1234 x ", "ABC-1234 x -1", "ABC-1234 x +1", "ABC-1234 x 1 ",
		"ABC-1234 x 10000", "ABC-1234 x 1e3", "ABC-1234 x \u0661",
	} {
		if linePattern.FindStringSubmatch(text) != nil {
			t.Errorf("%q should not match", text)
		}
	}
}
