package render

import (
	"bytes"
	"strconv"
)

type Row struct {
	Name  string
	Count int
}

func Rows(rows []Row) string {
	var buf bytes.Buffer
	for _, r := range rows {
		_, _ = buf.WriteString(r.Name)
		_ = buf.WriteByte('\t')
		_, _ = buf.WriteString(strconv.Itoa(r.Count))
		_ = buf.WriteByte('\n')
	}
	return buf.String()
}
