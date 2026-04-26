package main

import (
	"log"
	"os"
	"time"

	"github.com/SvenDowideit/newsapp/android/internal/cache"
	appstate "github.com/SvenDowideit/newsapp/android/internal/state"
	"github.com/SvenDowideit/newsapp/android/internal/ui"
	"github.com/go-drift/drift/pkg/core"
	"github.com/go-drift/drift/pkg/drift"
	"github.com/go-drift/drift/pkg/widgets"
)

const (
	defaultAPIURL = "http://newsapp.local:8000" // mDNS — falls back to NEWSAGG_API env var
	cacheFile     = "newsapp.db"
	prefetchCount = 50
)

func main() {
	apiURL := os.Getenv("NEWSAGG_API")
	if apiURL == "" {
		apiURL = defaultAPIURL
	}

	store, err := cache.Open(cacheFile)
	if err != nil {
		log.Fatalf("cache: %v", err)
	}
	defer store.Close()

	app := appstate.New(apiURL, store)

	if cached, err := store.LoadItems(); err == nil && len(cached) > 0 {
		app.SetFeedItems(cached)
	}

	drift.Run(drift.NewApp(buildRootWidget(app)))
}

func buildRootWidget(app *appstate.App) core.Widget {
	type uiState struct {
		page        appstate.Page
		contextOpen bool
	}

	return core.Stateful(
		func() uiState {
			app.Mu.Lock()
			defer app.Mu.Unlock()
			return uiState{page: app.CurrentPage, contextOpen: app.ContextOpen}
		},
		func(state uiState, _ core.BuildContext, setState func(func(uiState) uiState)) core.Widget {
			rebuild := func() {
				drift.Dispatch(func() {
					app.Mu.Lock()
					s := uiState{page: app.CurrentPage, contextOpen: app.ContextOpen}
					app.Mu.Unlock()
					setState(func(_ uiState) uiState { return s })
				})
			}

			// Kick off initial feed load
			if state.page == appstate.PageFeed && len(app.FeedItems) == 0 {
				go func() {
					refreshFeed(app)
					rebuild()
				}()
			}

			if state.contextOpen {
				return ui.ContextMenu(func(action string) {
					handleMenuAction(action, app)
					rebuild()
				})
			}

			switch state.page {
			case appstate.PageFeed:
				app.Mu.Lock()
				items := app.FeedItems
				app.Mu.Unlock()
				return ui.FeedPage(items, func(idx int) {
					app.Mu.Lock()
					app.CurrentIndex = idx
					app.CurrentPage = appstate.PageItem
					app.ItemPage = 0
					app.Mu.Unlock()
					rebuild()
				})

			case appstate.PageItem:
				item := app.CurrentItem()
				app.Mu.Lock()
				itemPage := app.ItemPage
				expanded := app.ExpandedItem
				app.Mu.Unlock()
				return ui.ItemPage(item, expanded, itemPage, func(gesture string) {
					handleItemGesture(gesture, app, rebuild)
				})

			default:
				return widgets.Center{Child: widgets.Text{Content: "Unknown page", Style: ui.BodyStyle()}}
			}
		},
	)
}

func handleItemGesture(gesture string, app *appstate.App, rebuild func()) {
	item := app.CurrentItem()
	if item == nil {
		return
	}
	id := item.ID

	switch gesture {
	case "next_item":
		if app.NextItem() {
			rebuild()
		}
	case "prev_item":
		if app.PrevItem() {
			rebuild()
		}
	case "discard":
		go app.API.Discard(id)
		app.NextItem()
		rebuild()
	case "expand":
		go func() {
			expanded, err := app.API.ExpandItem(id)
			if err == nil {
				app.Mu.Lock()
				app.ExpandedItem = expanded
				app.Mu.Unlock()
				go app.API.Follow(id)
				rebuild()
			}
		}()
	case "menu":
		app.Mu.Lock()
		app.ContextOpen = true
		app.Mu.Unlock()
		rebuild()
	case "interest_up":
		go app.API.AdjustInterest(id, "up")
	case "interest_down":
		go app.API.AdjustInterest(id, "down")
	}
}

func handleMenuAction(action string, app *appstate.App) {
	item := app.CurrentItem()
	id := int64(0)
	if item != nil {
		id = item.ID
	}

	app.Mu.Lock()
	app.ContextOpen = false
	app.Mu.Unlock()

	switch action {
	case "save":
		if id != 0 {
			go app.API.Save(id)
		}
	case "send":
		if item != nil && item.CanonicalURL != nil {
			log.Printf("share: %s", *item.CanonicalURL)
		}
	case "interest_up":
		if id != 0 {
			go app.API.AdjustInterest(id, "up")
		}
	case "interest_down":
		if id != 0 {
			go app.API.AdjustInterest(id, "down")
		}
	case "discard":
		if id != 0 {
			go app.API.Discard(id)
			app.NextItem()
		}
	}
}

func refreshFeed(app *appstate.App) {
	for {
		feed, err := app.API.GetFeed(1, prefetchCount, true)
		if err != nil {
			log.Printf("feed refresh error: %v", err)
		} else if len(feed.Items) > 0 {
			app.SetFeedItems(feed.Items)
			_ = app.Cache.SaveItems(feed.Items)
			_ = app.Cache.Evict(200)
		}
		time.Sleep(2 * time.Minute)
	}
}
