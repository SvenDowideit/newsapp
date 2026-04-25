package ui

import (
	"fmt"
	"strings"

	"github.com/SvenDowideit/newsapp/android/internal/api/models"
	"github.com/go-drift/drift"
)

const linesPerPage = 18 // approximate lines per eink screen

// ItemPage renders a single cluster item, paginated.
// currentPage is 0-indexed. totalPages is set by this function.
// onGesture receives gesture strings: "next_page","prev_page","next_item","prev_item","discard","expand","menu"
func ItemPage(
	item *models.ClusterItem,
	expanded *models.ExpandedItem,
	currentPage int,
	onGesture func(string),
) drift.Widget {
	if item == nil {
		return drift.Center(drift.Text("No item", BodyStyle()))
	}

	// Build full text blocks
	var blocks []string
	blocks = append(blocks, item.Headline)
	blocks = append(blocks, "")
	blocks = append(blocks, item.Summary)
	if len(item.KeyPoints) > 0 {
		blocks = append(blocks, "")
		for _, kp := range item.KeyPoints {
			blocks = append(blocks, "• "+kp)
		}
	}
	if expanded != nil {
		blocks = append(blocks, "")
		blocks = append(blocks, "── Full article ──")
		blocks = append(blocks, expanded.FullSummary)
	}

	topics := strings.Join(item.Topics, " · ")
	meta := fmt.Sprintf("%s · %d sources", topics, item.ItemCount)
	if item.IsBreaking {
		meta = "BREAKING · " + meta
	}

	// Simple pagination: split blocks into pages of ~linesPerPage text lines
	pages := paginateBlocks(blocks, linesPerPage)
	totalPages := len(pages)
	if currentPage >= totalPages {
		currentPage = totalPages - 1
	}
	if currentPage < 0 {
		currentPage = 0
	}
	pageContent := pages[currentPage]

	widgets := make([]drift.Widget, 0, len(pageContent)+3)
	for _, line := range pageContent {
		if line == "" {
			widgets = append(widgets, drift.SizedBox(drift.Size{Height: 8}))
		} else {
			style := BodyStyle()
			if line == pageContent[0] && currentPage == 0 {
				style = HeadlineStyle()
			}
			widgets = append(widgets, drift.Text(line, style))
		}
	}

	// Page indicator
	pageIndicator := drift.Text(
		fmt.Sprintf("%d / %d", currentPage+1, totalPages),
		MetaStyle(),
	)

	// Gesture zones overlay
	content := drift.Stack([]drift.Widget{
		drift.Column(append(widgets,
			drift.Spacer(),
			drift.Text(meta, MetaStyle()),
			drift.Padding(pageIndicator, drift.Insets{Top: 8}),
		)),
		// Left tap zone → prev page / reduce interest
		drift.Positioned(
			drift.GestureDetector(
				drift.SizedBox(drift.Size{Width: 80, Height: -1}),
				drift.GestureCallbacks{
					OnTap:        func() { onGesture("prev_page") },
					OnSwipeUp:    func() { onGesture("next_item") },
					OnSwipeDown:  func() { onGesture("prev_item") },
					OnSwipeLeft:  func() { onGesture("discard") },
					OnSwipeRight: func() { onGesture("expand") },
					OnLongPress:  func() { onGesture("menu") },
				},
			),
			drift.Position{Left: 0, Top: 0, Bottom: 0},
		),
		// Right tap zone → next page / increase interest
		drift.Positioned(
			drift.GestureDetector(
				drift.SizedBox(drift.Size{Width: 80, Height: -1}),
				drift.GestureCallbacks{
					OnTap:        func() { onGesture("next_page") },
					OnSwipeUp:    func() { onGesture("next_item") },
					OnSwipeDown:  func() { onGesture("prev_item") },
					OnSwipeLeft:  func() { onGesture("discard") },
					OnSwipeRight: func() { onGesture("expand") },
					OnLongPress:  func() { onGesture("menu") },
				},
			),
			drift.Position{Right: 0, Top: 0, Bottom: 0},
		),
	})

	return drift.Padding(content, EinkTheme.Padding)
}

// paginateBlocks splits lines into pages of at most maxLines lines.
func paginateBlocks(blocks []string, maxLines int) [][]string {
	var pages [][]string
	var current []string
	for _, b := range blocks {
		current = append(current, b)
		if len(current) >= maxLines {
			pages = append(pages, current)
			current = nil
		}
	}
	if len(current) > 0 {
		pages = append(pages, current)
	}
	if len(pages) == 0 {
		pages = [][]string{{"(empty)"}}
	}
	return pages
}
