package stage

import "os"

// Workdir is a private scratch directory for one run. os.MkdirTemp creates
// it with mode 0700 under a fresh random name, so only this user can enter it.
type Workdir struct {
	dir string
}

func NewWorkdir() (*Workdir, error) {
	dir, err := os.MkdirTemp("", "stage-")
	if err != nil {
		return nil, err
	}
	return &Workdir{dir: dir}, nil
}

func (w *Workdir) Close() error { return os.RemoveAll(w.dir) }
