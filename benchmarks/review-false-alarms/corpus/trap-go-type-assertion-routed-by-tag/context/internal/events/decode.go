package events

import (
	"encoding/json"
	"fmt"
)

type Event struct {
	Type    string
	Payload any
}

type Order struct {
	Account     string `json:"account"`
	AmountCents int64  `json:"amount_cents"`
}

type Refund struct {
	ID          string `json:"id"`
	Account     string `json:"account"`
	AmountCents int64  `json:"amount_cents"`
}

var payloadTypes = map[string]func() any{
	"order":  func() any { return new(Order) },
	"refund": func() any { return new(Refund) },
}

// Decode is the only constructor of Event: Payload's type always follows Type.
func Decode(data []byte) (Event, error) {
	var envelope struct {
		Type    string          `json:"type"`
		Payload json.RawMessage `json:"payload"`
	}
	if err := json.Unmarshal(data, &envelope); err != nil {
		return Event{}, err
	}
	newPayload, ok := payloadTypes[envelope.Type]
	if !ok {
		return Event{}, fmt.Errorf("unknown event type %q", envelope.Type)
	}
	payload := newPayload()
	if err := json.Unmarshal(envelope.Payload, payload); err != nil {
		return Event{}, err
	}
	return Event{Type: envelope.Type, Payload: payload}, nil
}
