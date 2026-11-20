package order

import "regexp"

// linePattern is the whole grammar of an order line: a SKU, " x ", and a
// quantity of one to four ASCII digits. Nothing else matches.
var linePattern = regexp.MustCompile(`^([A-Z]{3}-[0-9]{4}) x ([0-9]{1,4})$`)
