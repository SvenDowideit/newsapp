package cache

import (
	"encoding/json"
	"strconv"

	bolt "go.etcd.io/bbolt"

	"github.com/svenDowideit/newsapp/internal/api/models"
)

var bucketItems = []byte("items")

type Store struct {
	db *bolt.DB
}

func Open(path string) (*Store, error) {
	db, err := bolt.Open(path, 0600, nil)
	if err != nil {
		return nil, err
	}
	err = db.Update(func(tx *bolt.Tx) error {
		_, err := tx.CreateBucketIfNotExists(bucketItems)
		return err
	})
	return &Store{db: db}, err
}

func (s *Store) Close() error { return s.db.Close() }

func (s *Store) SaveItems(items []models.ClusterItem) error {
	return s.db.Update(func(tx *bolt.Tx) error {
		b := tx.Bucket(bucketItems)
		for _, item := range items {
			data, err := json.Marshal(item)
			if err != nil {
				continue
			}
			if err := b.Put([]byte(strconv.FormatInt(item.ID, 10)), data); err != nil {
				return err
			}
		}
		return nil
	})
}

func (s *Store) LoadItems() ([]models.ClusterItem, error) {
	var items []models.ClusterItem
	err := s.db.View(func(tx *bolt.Tx) error {
		b := tx.Bucket(bucketItems)
		return b.ForEach(func(_, v []byte) error {
			var item models.ClusterItem
			if err := json.Unmarshal(v, &item); err == nil {
				items = append(items, item)
			}
			return nil
		})
	})
	return items, err
}

// Evict removes all items beyond keepN (oldest first by bucket key order).
func (s *Store) Evict(keepN int) error {
	return s.db.Update(func(tx *bolt.Tx) error {
		b := tx.Bucket(bucketItems)
		total := b.Stats().KeyN
		toDelete := total - keepN
		if toDelete <= 0 {
			return nil
		}
		c := b.Cursor()
		for k, _ := c.First(); k != nil && toDelete > 0; k, _ = c.Next() {
			if err := b.Delete(k); err != nil {
				return err
			}
			toDelete--
		}
		return nil
	})
}
