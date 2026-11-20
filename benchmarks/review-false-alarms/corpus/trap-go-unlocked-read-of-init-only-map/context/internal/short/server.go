package short

import (
	"net/http"
	"strings"
	"sync"
)

type Server struct {
	mu      sync.Mutex
	hits    map[string]int
	targets map[string]string
	aliases map[string]string
}

func NewServer(targets map[string]string) *Server {
	return &Server{hits: map[string]int{}, targets: targets, aliases: map[string]string{}}
}

// LoadAliases maps extra names onto existing short codes.
func (s *Server) LoadAliases(aliases map[string]string) {
	for name, code := range aliases {
		s.aliases[name] = code
	}
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	code := strings.TrimPrefix(r.URL.Path, "/")
	if alias, ok := s.aliases[code]; ok {
		code = alias
	}
	target, ok := s.targets[code]
	if !ok {
		http.NotFound(w, r)
		return
	}
	s.mu.Lock()
	s.hits[code]++
	s.mu.Unlock()
	http.Redirect(w, r, target, http.StatusFound)
}
