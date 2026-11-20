package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"

	"example.com/short/internal/short"
)

func readMap(path string) map[string]string {
	data, err := os.ReadFile(path)
	if err != nil {
		log.Fatal(err)
	}
	m := map[string]string{}
	if err := json.Unmarshal(data, &m); err != nil {
		log.Fatal(err)
	}
	return m
}

func main() {
	srv := short.NewServer(readMap("targets.json"))
	srv.LoadAliases(readMap("aliases.json"))
	log.Fatal(http.ListenAndServe(":8080", srv))
}
