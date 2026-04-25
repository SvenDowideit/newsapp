package models

import "time"

type ClusterItem struct {
	ID            int64     `json:"id"`
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
	FirstSeenAt   time.Time `json:"first_seen_at"`
	LatestSeenAt  time.Time `json:"latest_seen_at"`
	CanonicalURL  *string   `json:"canonical_url"`
	Headline      string    `json:"headline"`
	Summary       string    `json:"summary"`
	KeyPoints     []string  `json:"key_points"`
	Topics        []string  `json:"topics"`
	SourceIDs     []string  `json:"source_ids"`
	ItemCount     int       `json:"item_count"`
	IsBreaking    bool      `json:"is_breaking"`
	CombinedScore float64   `json:"combined_score"`
}

type FeedResponse struct {
	Items    []ClusterItem `json:"items"`
	Page     int           `json:"page"`
	PageSize int           `json:"page_size"`
	Total    int           `json:"total"`
}

type ExpandedItem struct {
	ID          int64    `json:"id"`
	Headline    string   `json:"headline"`
	FullSummary string   `json:"full_summary"`
	KeyPoints   []string `json:"key_points"`
	SourceURLs  []string `json:"source_urls"`
	Topics      []string `json:"topics"`
}

type ReadEventBody struct {
	DurationSeconds *int  `json:"duration_seconds,omitempty"`
	FullyRead       *bool `json:"fully_read,omitempty"`
}

type InterestAdjustBody struct {
	Direction string `json:"direction"` // "up" or "down"
}
