package stage

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
)

// WriteOnce stores an artifact under the work dir unless one is already there.
func (w *Workdir) WriteOnce(name string, data []byte) (bool, error) {
	path := filepath.Join(w.dir, name)
	if _, err := os.Stat(path); err == nil {
		return false, nil
	} else if !errors.Is(err, fs.ErrNotExist) {
		return false, err
	}
	return true, os.WriteFile(path, data, 0o600)
}
