package order

import (
	"fmt"
	"strconv"
)

type Line struct {
	SKU      string
	Quantity int
}

// Parse reads one order line such as "ABC-1234 x 12".
func Parse(text string) (Line, error) {
	m := linePattern.FindStringSubmatch(text)
	if m == nil {
		return Line{}, fmt.Errorf("order line %q: want SKU x QUANTITY", text)
	}
	quantity, _ := strconv.Atoi(m[2])
	if quantity == 0 {
		return Line{}, fmt.Errorf("order line %q: quantity must be positive", text)
	}
	return Line{SKU: m[1], Quantity: quantity}, nil
}
