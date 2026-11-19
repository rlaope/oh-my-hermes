package store

import (
	"context"
	"database/sql"
)

type Store struct {
	db *sql.DB
}

func (s *Store) Names(ctx context.Context) ([]string, error) {
	rows, err := s.db.QueryContext(ctx, "SELECT name FROM users WHERE active ORDER BY name")
	defer rows.Close()
	if err != nil {
		return nil, err
	}
	var names []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		names = append(names, name)
	}
	return names, rows.Err()
}
