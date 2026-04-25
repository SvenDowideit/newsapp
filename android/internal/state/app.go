package state

import (
	"sync"

	"github.com/SvenDowideit/newsapp/android/internal/api"
	"github.com/SvenDowideit/newsapp/android/internal/api/models"
	"github.com/SvenDowideit/newsapp/android/internal/cache"
)

// Page identifies the current screen.
type Page int

const (
	PageFeed Page = iota
	PageItem
	PageContextMenu
	PageSources
)

// App holds the full application state.
type App struct {
	Mu sync.Mutex

	CurrentPage  Page
	FeedItems    []models.ClusterItem
	CurrentIndex int
	ItemPage     int
	ContextOpen  bool

	ExpandedItem *models.ExpandedItem

	API   *api.Client
	Cache *cache.Store
}

func New(apiBaseURL string, cacheStore *cache.Store) *App {
	return &App{
		API:   api.New(apiBaseURL),
		Cache: cacheStore,
	}
}

func (a *App) CurrentItem() *models.ClusterItem {
	a.Mu.Lock()
	defer a.Mu.Unlock()
	if a.CurrentIndex < 0 || a.CurrentIndex >= len(a.FeedItems) {
		return nil
	}
	item := a.FeedItems[a.CurrentIndex]
	return &item
}

func (a *App) SetFeedItems(items []models.ClusterItem) {
	a.Mu.Lock()
	defer a.Mu.Unlock()
	a.FeedItems = items
	a.CurrentIndex = 0
	a.ItemPage = 0
}

func (a *App) NextItem() bool {
	a.Mu.Lock()
	defer a.Mu.Unlock()
	if a.CurrentIndex+1 >= len(a.FeedItems) {
		return false
	}
	a.CurrentIndex++
	a.ItemPage = 0
	a.ExpandedItem = nil
	return true
}

func (a *App) PrevItem() bool {
	a.Mu.Lock()
	defer a.Mu.Unlock()
	if a.CurrentIndex <= 0 {
		return false
	}
	a.CurrentIndex--
	a.ItemPage = 0
	a.ExpandedItem = nil
	return true
}

func (a *App) NextPage() { a.Mu.Lock(); a.ItemPage++; a.Mu.Unlock() }
func (a *App) PrevPage() {
	a.Mu.Lock()
	if a.ItemPage > 0 {
		a.ItemPage--
	}
	a.Mu.Unlock()
}
