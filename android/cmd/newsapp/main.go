package main

import (
	"fmt"
	"log"
	"os"
	"time"

	"github.com/go-drift/drift"
	"github.com/svenDowideit/newsapp/internal/api/models"
	"github.com/svenDowideit/newsapp/internal/cache"
	appstate "github.com/svenDowideit/newsapp/internal/state"
	"github.com/svenDowideit/newsapp/internal/ui"
)

const (
	defaultAPIURL   = "http://100.64.0.1:8000" // Tailscale default range
	cacheFile       = "newsapp.db"
	prefetchCount   = 50
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

	// Prefetch from cache first, then refresh from API
	if cached, err := store.LoadItems(); err == nil && len(cached) > 0 {
		app.SetFeedItems(cached)
	}
	go refreshFeed(app)

	drift.Run(drift.AppConfig{
		Title:  "News",
		Theme:  ui.EinkTheme,
		Width:  540,
		Height: 960,
	}, func(ctx *drift.BuildContext) drift.Widget {
		return buildRoot(ctx, app)
	})
}

func buildRoot(ctx *drift.BuildContext, app *appstate.App) drift.Widget {
	app.mu.Lock()
	page := app.CurrentPage
	contextOpen := app.ContextOpen
	app.mu.Unlock()

	if contextOpen {
		return ui.ContextMenu(func(action string) {
			handleMenuAction(action, app, ctx)
		})
	}

	switch page {
	case appstate.PageFeed:
		return ui.FeedPage(app.FeedItems, func(idx int) {
			app.mu.Lock()
			app.CurrentIndex = idx
			app.CurrentPage = appstate.PageItem
			app.ItemPage = 0
			app.mu.Unlock()
			ctx.Rebuild()
		})

	case appstate.PageItem:
		item := app.CurrentItem()
		app.mu.Lock()
		itemPage := app.ItemPage
		expanded := app.ExpandedItem
		app.mu.Unlock()

		return ui.ItemPage(item, expanded, itemPage, func(gesture string) {
			handleItemGesture(gesture, app, ctx)
		})

	default:
		return drift.Center(drift.Text("Unknown page", ui.BodyStyle()))
	}
}

func handleItemGesture(gesture string, app *appstate.App, ctx *drift.BuildContext) {
	item := app.CurrentItem()
	if item == nil {
		return
	}
	id := item.ID

	switch gesture {
	case "next_page":
		app.NextPage()
		ctx.Rebuild()

	case "prev_page":
		app.PrevPage()
		ctx.Rebuild()

	case "next_item":
		if app.NextItem() {
			ctx.Rebuild()
		}

	case "prev_item":
		if app.PrevItem() {
			ctx.Rebuild()
		}

	case "discard":
		go app.API.Discard(id)
		app.NextItem()
		ctx.Rebuild()

	case "expand":
		go func() {
			expanded, err := app.API.ExpandItem(id)
			if err == nil {
				app.mu.Lock()
				app.ExpandedItem = expanded
				app.mu.Unlock()
				go app.API.Follow(id)
				ctx.Rebuild()
			}
		}()

	case "menu":
		app.mu.Lock()
		app.ContextOpen = true
		app.mu.Unlock()
		ctx.Rebuild()
	}
}

func handleMenuAction(action string, app *appstate.App, ctx *drift.BuildContext) {
	item := app.CurrentItem()
	id := int64(0)
	if item != nil {
		id = item.ID
	}

	app.mu.Lock()
	app.ContextOpen = false
	app.mu.Unlock()

	switch action {
	case "save":
		if id != 0 {
			go app.API.Save(id)
		}
	case "send":
		if item != nil && item.CanonicalURL != nil {
			drift.ShareURL(*item.CanonicalURL)
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
	ctx.Rebuild()
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

// recordReadTime sends a read event when the user spends time on an item.
func recordReadTime(app *appstate.App, id int64, start time.Time) {
	dur := int(time.Since(start).Seconds())
	if dur < 2 {
		return
	}
	go func() {
		t := true
		_ = app.API.RecordRead(id, &dur, &t)
	}()
}

func init() {
	// Suppress "declared and not used" for fmt in simple builds.
	_ = fmt.Sprintf
}
