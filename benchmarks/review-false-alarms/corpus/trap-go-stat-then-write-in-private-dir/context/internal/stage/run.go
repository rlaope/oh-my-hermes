package stage

// Run executes the steps one after another; nothing else holds the Workdir.
func Run(steps []Step) error {
	w, err := NewWorkdir()
	if err != nil {
		return err
	}
	defer w.Close()
	for _, step := range steps {
		data, err := step.Produce()
		if err != nil {
			return err
		}
		if _, err := w.WriteOnce(step.Name, data); err != nil {
			return err
		}
	}
	return nil
}

type Step struct {
	Name    string
	Produce func() ([]byte, error)
}
