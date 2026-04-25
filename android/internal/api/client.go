package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"time"

	"github.com/SvenDowideit/newsapp/android/internal/api/models"
)

// Client talks to the newsagg backend REST API.
type Client struct {
	base       string
	httpClient *http.Client
}

func New(baseURL string) *Client {
	return &Client{
		base: baseURL,
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

func (c *Client) GetFeed(page, pageSize int, active bool) (*models.FeedResponse, error) {
	u, _ := url.Parse(c.base + "/feed")
	q := u.Query()
	q.Set("page", strconv.Itoa(page))
	q.Set("page_size", strconv.Itoa(pageSize))
	if active {
		q.Set("active", "true")
	}
	u.RawQuery = q.Encode()

	resp, err := c.httpClient.Get(u.String())
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("feed: status %d", resp.StatusCode)
	}
	var out models.FeedResponse
	return &out, json.NewDecoder(resp.Body).Decode(&out)
}

func (c *Client) ExpandItem(id int64) (*models.ExpandedItem, error) {
	url := fmt.Sprintf("%s/items/%d/expand", c.base, id)
	resp, err := c.httpClient.Post(url, "application/json", nil)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("expand: status %d", resp.StatusCode)
	}
	var out models.ExpandedItem
	return &out, json.NewDecoder(resp.Body).Decode(&out)
}

func (c *Client) RecordRead(id int64, durationSec *int, fullyRead *bool) error {
	body := models.ReadEventBody{DurationSeconds: durationSec, FullyRead: fullyRead}
	return c.postJSON(fmt.Sprintf("/items/%d/read", id), body, http.StatusNoContent)
}

func (c *Client) Discard(id int64) error {
	return c.postJSON(fmt.Sprintf("/items/%d/discard", id), nil, http.StatusNoContent)
}

func (c *Client) Follow(id int64) error {
	return c.postJSON(fmt.Sprintf("/items/%d/follow", id), nil, http.StatusNoContent)
}

func (c *Client) Save(id int64) error {
	return c.postJSON(fmt.Sprintf("/items/%d/save", id), nil, http.StatusNoContent)
}

func (c *Client) AdjustInterest(id int64, direction string) error {
	body := models.InterestAdjustBody{Direction: direction}
	return c.postJSON(fmt.Sprintf("/items/%d/interest", id), body, http.StatusNoContent)
}

func (c *Client) postJSON(path string, body any, expectedStatus int) error {
	var r io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		r = bytes.NewReader(b)
	} else {
		r = bytes.NewReader(nil)
	}
	resp, err := c.httpClient.Post(c.base+path, "application/json", r)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != expectedStatus {
		return fmt.Errorf("POST %s: status %d", path, resp.StatusCode)
	}
	return nil
}
